# -*- coding: utf-8 -*-
"""
GraaS MCP Server Automation Runner for Pending Order Reports
"""
import asyncio
import json
import os
import io
import sys
import logging
import requests
import pandas as pd
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("mcp_automation.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("mcp_automation")

# Import local modules
try:
    from order_processor import process_and_validate_orders
    from email_sender import send_seller_report_email, test_smtp_connection
except ImportError:
    # If run from parent directory or other path contexts
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from order_processor import process_and_validate_orders
    from email_sender import send_seller_report_email, test_smtp_connection

CONFIG_FILE = "mcp_config.json"

def load_config():
    """Load configuration from JSON file."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
    if not os.path.exists(config_path):
        logger.error(f"Configuration file not found at {config_path}")
        raise FileNotFoundError(f"Configuration file not found: {CONFIG_FILE}")
    
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_access_token(config):
    """Refresh and return access token via OAuth 2.1."""
    refresh_token = config.get("refresh_token")
    token_url = config.get("token_url")
    client_id = config.get("client_id")
    
    if not refresh_token or "placeholder" in refresh_token.lower():
        raise ValueError("Valid 'refresh_token' is required in mcp_config.json.")
        
    payload = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    if client_id and "placeholder" not in client_id.lower():
        payload["client_id"] = client_id
        
    logger.info(f"Refreshing access token from {token_url}...")
    response = requests.post(token_url, data=payload)
    response.raise_for_status()
    token_data = response.json()
    return token_data["access_token"]

def register_mcp_client(config):
    """Perform dynamic client registration with the GraaS authorization server."""
    register_url = config.get("token_url").replace("/token", "/register")
    logger.info(f"Registering dynamic client at {register_url}...")
    
    payload = {
        "client_name": "PUMA Pending Order Report Automation Runner",
        "redirect_uris": ["http://localhost:8000/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "scope": "read:data read:schema",
        "token_endpoint_auth_method": "none"
    }
    
    try:
        response = requests.post(register_url, json=payload)
        response.raise_for_status()
        reg_info = response.json()
        logger.info("Client successfully registered!")
        logger.info(f"Client ID: {reg_info.get('client_id')}")
        
        # Save client_id to configuration
        config["client_id"] = reg_info.get("client_id")
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        logger.info(f"Updated configuration file with Client ID: {CONFIG_FILE}")
        return reg_info
    except Exception as e:
        logger.error(f"Failed to dynamically register client: {str(e)}")
        raise

async def fetch_snowflake_data(access_token, mcp_url, query):
    """Connect to the MCP server and run a database query using the available tools."""
    from mcp import ClientSession
    from mcp.client.sse import sse_client
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    logger.info(f"Connecting to MCP Server: {mcp_url}...")
    async with sse_client(mcp_url, headers=headers) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            logger.info("Initializing MCP Session...")
            await session.initialize()
            
            # List available tools to find the SQL querying tool
            logger.info("Retrieving available tools...")
            tools_result = await session.list_tools()
            tools = tools_result.tools
            
            query_tool = None
            # Find a tool designed for querying Snowflake
            for tool in tools:
                if any(x in tool.name.lower() for x in ["query", "sql", "execute"]):
                    query_tool = tool
                    break
                    
            if not query_tool:
                # Default fallback to first tool if no exact matches found
                if tools:
                    query_tool = tools[0]
                    logger.warning(f"No explicit sql/query tool name found. Defaulting to first tool: {query_tool.name}")
                else:
                    raise RuntimeError("No tools are exposed by this GraaS MCP server!")
            
            logger.info(f"Executing query using tool '{query_tool.name}': {query}")
            
            # Determine argument name from schema or fallback to 'query' or 'sql'
            arg_name = "query"
            if query_tool.inputSchema and "properties" in query_tool.inputSchema:
                properties = query_tool.inputSchema["properties"]
                if "sql" in properties:
                    arg_name = "sql"
                elif "query" in properties:
                    arg_name = "query"
                elif properties:
                    arg_name = list(properties.keys())[0] # Pick first property
            
            result = await session.call_tool(
                name=query_tool.name,
                arguments={arg_name: query}
            )
            
            # Check the tool result format.
            # Normal MCP tool result returns content blocks.
            records = []
            if result and hasattr(result, "content") and result.content:
                for block in result.content:
                    if hasattr(block, "text") and block.text:
                        try:
                            # Attempt to parse json structure from response text block
                            data = json.loads(block.text)
                            if isinstance(data, list):
                                records = data
                            elif isinstance(data, dict) and "rows" in data:
                                records = data["rows"]
                            else:
                                records = [data]
                        except Exception:
                            logger.warning("Could not parse JSON response block directly. Raw content block text will be logged.")
                            logger.info(block.text)
                            
            logger.info(f"Query returned {len(records)} records.")
            return records

def convert_records_to_csv_file(records, filename):
    """Convert JSON list of dicts to CSV BytesIO object with a name attribute."""
    df = pd.DataFrame(records)
    if df.empty:
        logger.warning(f"No records found for {filename}. Creating an empty DataFrame.")
    
    csv_buffer = io.BytesIO()
    # Write as UTF-8 with BOM for Excel compatibility
    df.to_csv(csv_buffer, index=False, encoding="utf-8-sig")
    csv_buffer.seek(0)
    csv_buffer.name = filename
    return csv_buffer

async def run_automation():
    """Main automated workflow execution."""
    logger.info("Starting automated pending order report process...")
    
    # 1. Load Config
    config = load_config()
    
    # 2. Get Access Token
    try:
        access_token = get_access_token(config)
    except Exception as e:
        logger.error(f"Authentication failed: {str(e)}")
        logger.info("If you need to register a new client ID first, run this script with --register argument.")
        return False
        
    # 3. Pull Data from Snowflake via MCP
    mcp_url = config.get("mcp_url")
    queries = config.get("queries", {})
    
    logger.info("Fetching reports from Snowflake via MCP Server...")
    try:
        pending_records = await fetch_snowflake_data(access_token, mcp_url, queries.get("pending"))
        tc_records = await fetch_snowflake_data(access_token, mcp_url, queries.get("tc"))
        oms_records = await fetch_snowflake_data(access_token, mcp_url, queries.get("oms"))
    except Exception as e:
        logger.error(f"Failed to fetch data from MCP server: {str(e)}")
        return False
        
    # 4. Format into memory file-like objects to satisfy processor
    pending_file = convert_records_to_csv_file(pending_records, "pending_orders.csv")
    tc_file = convert_records_to_csv_file(tc_records, "tc_report.csv")
    oms_file = convert_records_to_csv_file(oms_records, "oms_report.csv")
    
    # 5. Run process validation
    logger.info("Running order process and validation analyzer...")
    try:
        res = process_and_validate_orders(
            pending_file=pending_file,
            tc_file=tc_file,
            oms_file=oms_file
        )
        enriched_df = res["enriched_pending_df"]
        discrepancies_df = res["discrepancies_df"]
        summary = res["summary"]
        logger.info(f"Validation complete! Enriched Orders: {summary.get('total_pending_orders')}, Discrepancies: {summary.get('total_discrepancies')}")
    except Exception as e:
        logger.error(f"Order validation processing failed: {str(e)}")
        return False
        
    # 6. Check SMTP connection first
    smtp_config = {
        "host": config.get("smtp_host"),
        "port": config.get("smtp_port"),
        "user": config.get("smtp_user"),
        "password": config.get("smtp_password"),
        "sender_email": config.get("smtp_sender_email"),
        "use_tls": config.get("smtp_use_tls", True)
    }
    
    logger.info("Verifying SMTP connection...")
    conn_ok, conn_msg = test_smtp_connection(
        smtp_config["host"], smtp_config["port"],
        smtp_config["user"], smtp_config["password"],
        smtp_config["use_tls"]
    )
    if not conn_ok:
        logger.error(f"SMTP Connection validation failed: {conn_msg}. Aborting email send.")
        return False
        
    # 7. Send report to seller
    seller_email = config.get("seller_email")
    logger.info(f"Sending email report to seller GED ({seller_email})...")
    email_ok, email_msg = send_seller_report_email(
        smtp_config=smtp_config,
        seller_name="GED",
        recipient_email=seller_email,
        seller_df=enriched_df,
        discrepancies_df=discrepancies_df
    )
    
    if email_ok:
        logger.info("Automation workflow executed successfully. Email sent.")
        return True
    else:
        logger.error(f"Failed to email report: {email_msg}")
        return False

def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "--register":
            # Dynamic Registration
            config = load_config()
            register_mcp_client(config)
            return
        elif arg == "--test-smtp":
            config = load_config()
            ok, msg = test_smtp_connection(
                config.get("smtp_host"), config.get("smtp_port"),
                config.get("smtp_user"), config.get("smtp_password"),
                config.get("smtp_use_tls", True)
            )
            print(f"SMTP Status: {ok}, Details: {msg}")
            return
        elif arg == "--test-mcp":
            config = load_config()
            try:
                access_token = get_access_token(config)
                print("Access token retrieved successfully!")
                print("Testing connection and listing tools on GraaS MCP server...")
                asyncio.run(fetch_snowflake_data(access_token, config.get("mcp_url"), "SELECT 1"))
            except Exception as e:
                print(f"MCP Test failed: {str(e)}")
            return
            
    # Default run
    success = asyncio.run(run_automation())
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
