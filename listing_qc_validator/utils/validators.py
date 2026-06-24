import re
import datetime
import pandas as pd
import numpy as np
import requests
from typing import Dict, List, Tuple

# Default allowed values
ALLOWED_GENDERS = ["men", "women", "unisex", "kids", "boys", "girls", "male", "female"]
ALLOWED_STATUSES = ["active", "inactive", "draft", "delisted", "suspended", "live", "on", "off", "yes", "no"]

URL_REGEX = re.compile(
    r'^(?:http|ftp)s?://' 
    r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|' 
    r'localhost|' 
    r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})' 
    r'(?::\d+)?' 
    r'(?:/?|[/?]\S+)$', re.IGNORECASE)

# Size Correction Dictionary
SIZE_CORRECTIONS = {
    "youth": "M",
    "adult": "L",
    "small": "S",
    "osfa": "One Size",
    "2xl": "XXL",
    "3xl": "XXXL",
    "4xl": "XXXXL",
    "5xl": "XXXXXL",
    "6xl": "XXXXXXL",
    "7xl": "XXXXXXXL"
}

# Common Malay e-commerce keywords for TikTok MY validations
MALAY_KEYWORDS = [
    r"\buntuk\b", r"\bdengan\b", r"\byang\b", r"\bpada\b", r"\badalah\b", r"\bdan\b",
    r"\blelaki\b", r"\bperempuan\b", r"\bwanita\b", r"\bsukan\b", r"\bkasut\b", r"\bbaju\b",
    r"\bseluar\b", r"\bkanak\b", r"\bbudak\b", r"\basli\b", r"\bmurah\b", r"\bsaiz\b",
    r"\bwarna\b", r"\bhitam\b", r"\bputih\b", r"\bmerah\b", r"\bbiru\b", r"\bhijau\b",
    r"\bkuning\b", r"\bberlari\b", r"\bjersey\b"
]

def _safe_str(val):
    if val is None:
        return ""
    if isinstance(val, (pd.Series, np.ndarray)):
        if len(val) == 0:
            return ""
        val = val.iloc[0] if hasattr(val, "iloc") else val[0]
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    return str(val).strip()

def _clean_sku(val):
    s = _safe_str(val)
    if re.fullmatch(r'\d+\.0', s):
        s = s[:-2]
    return s

def _normalise_cols(df):
    df.columns = [_safe_str(c) for c in df.columns]
    return df

def _normalise_article_no(val):
    s = _safe_str(val)
    if not s:
        return ""
    s = s.strip().upper()
    s = re.sub(r'[\s\-]+', '_', s)
    s = s.strip('_')
    return s

def _normalise_status(status):
    s = _safe_str(status).lower()
    if s in ("active", "1", "enabled", "yes", "y", "live", "listed", "on"):
        return "Yes"
    if s in ("inactive", "0", "disabled", "no", "n", "delisted", "unlisted", "deleted", "removed", "off"):
        return "No"
    return _safe_str(status)

def is_empty(val) -> bool:
    if val is None:
        return True
    if isinstance(val, (pd.Series, np.ndarray)):
        if len(val) == 0:
            return True
        val = val.iloc[0] if hasattr(val, "iloc") else val[0]
    try:
        if pd.isna(val):
            return True
    except Exception:
        pass
    val_str = str(val).strip()
    return val_str == "" or val_str.lower() in ["nan", "null", "<na>", "none"]

def clean_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, (pd.Series, np.ndarray)):
        if len(val) == 0:
            return ""
        val = val.iloc[0] if hasattr(val, "iloc") else val[0]
    if is_empty(val):
        return ""
    return str(val).strip()

def correct_size(sz: str) -> str:
    """Applies size corrections (e.g. Youth -> M, 2XL -> XXL)."""
    s = str(sz).strip()
    s_low = s.lower()
    if s_low in SIZE_CORRECTIONS:
        return SIZE_CORRECTIONS[s_low]
    return s

def clean_size_for_comparison(sz: str) -> str:
    s = str(sz).strip().lower()
    # Remove prefixes like 'uk:', 'us:', 'int:' case-insensitively, anywhere at the start
    s = re.sub(r'^(?:uk|us|int|uk:|us:|int:)[:\s\-]*', '', s)
    # Remove 'yrs-y', 'yrs-y', 'yrs', 'yr', 'y' variations at the end
    s = re.sub(r'[\s\-]*yrs?\-?y?\b', '', s)
    s = re.sub(r'[\s\-]*y\b', '', s)
    s = s.strip()
    
    # Check for W<waist> L<length> pattern (e.g. w28 l30 or w28l30)
    w_l_match = re.search(r'\bw\s*(\d+)\s*l\s*(\d+)\b', s)
    if w_l_match:
        s = f"{w_l_match.group(1)}/{w_l_match.group(2)}"
        
    # Normalize size corrections (e.g. 2xl -> xxl, 3xl -> xxxl) after stripping prefixes/suffixes
    if s in SIZE_CORRECTIONS:
        s = SIZE_CORRECTIONS[s].lower()
    return s

def is_footwear(product_name: str) -> bool:
    """Classifies footwear products based on title keywords."""
    name_low = str(product_name).lower()
    footwear_kws = ["shoe", "shoes", "sneaker", "sneakers", "sandal", "sandals", "slide", "slides", "boot", "boots", "slippers", "cleat", "cleats", "footwear"]
    return any(kw in name_low for kw in footwear_kws)

def is_kids_apparel(gender: str, product_name: str) -> bool:
    """Classifies Kids Apparel (Zalora Rus size rule)."""
    g_low = str(gender).lower()
    is_kid = g_low in ["kids", "boys", "girls"]
    # Apparel is anything that is NOT footwear
    return is_kid and not is_footwear(product_name)

def genders_are_compatible(g1: str, g2: str) -> bool:
    """Checks if two genders are compatible (e.g. Female and Women, Male and Men)."""
    g1_low = str(g1).strip().lower()
    g2_low = str(g2).strip().lower()
    if g1_low == g2_low:
        return True
    
    male_group = {"men", "mens", "male", "boy", "boys"}
    female_group = {"women", "womens", "female", "girl", "girls"}
    
    if g1_low in male_group and g2_low in male_group:
        return True
    if g1_low in female_group and g2_low in female_group:
        return True
    return False

# ── Reference Mappings Builders ───────────────────────────────────────────────

def build_content_maps(content_df: pd.DataFrame) -> Tuple[Dict, Dict, Dict, Dict, Dict, Dict, Dict, Dict, Dict]:
    """
    Builds lookup tables from Content File for UK, US, Russian size and color name mappings.
    Optimised using vectorised pandas operations for speed.
    """
    sku_to_article = {}
    sku_to_uksize = {}
    sku_to_ussize = {}
    sku_to_russize = {}
    sku_to_gender = {}
    sku_to_colorname = {}
    
    article_to_uksizes = {}
    article_to_ussizes = {}
    article_to_russizes = {}
    
    if content_df is not None and not content_df.empty:
        df_clean = content_df.copy()
        
        has_sku = "SKU" in df_clean.columns
        has_art = "Article No" in df_clean.columns
        has_uk = "uk_size" in df_clean.columns
        has_us = "us_size" in df_clean.columns
        has_rus = "rus_size" in df_clean.columns
        has_gender = "content_gender" in df_clean.columns
        has_color = "content_color_name" in df_clean.columns
        
        if has_sku:
            df_clean["SKU_clean"] = df_clean["SKU"].apply(_clean_sku)
            df_clean = df_clean[df_clean["SKU_clean"] != ""]
        else:
            df_clean["SKU_clean"] = ""
            
        if has_art:
            df_clean["Art_clean"] = df_clean["Article No"].apply(_normalise_article_no)
        else:
            df_clean["Art_clean"] = ""
            
        # Build SKU-level dictionary maps
        if not df_clean.empty and has_sku:
            sku_df = df_clean
            if has_art:
                sku_to_article = dict(zip(sku_df["SKU_clean"], sku_df["Art_clean"]))
            if has_uk:
                sku_to_uksize = dict(zip(sku_df["SKU_clean"], sku_df["uk_size"].fillna("").astype(str).str.strip()))
            if has_us:
                sku_to_ussize = dict(zip(sku_df["SKU_clean"], sku_df["us_size"].fillna("").astype(str).str.strip()))
            if has_rus:
                sku_to_russize = dict(zip(sku_df["SKU_clean"], sku_df["rus_size"].fillna("").astype(str).str.strip()))
            if has_gender:
                sku_to_gender = dict(zip(sku_df["SKU_clean"], sku_df["content_gender"].fillna("").astype(str).str.strip()))
            if has_color:
                sku_to_colorname = dict(zip(sku_df["SKU_clean"], sku_df["content_color_name"].fillna("").astype(str).str.strip()))
                
        # Build Article-level sets
        if "Art_clean" in df_clean.columns and not df_clean.empty:
            art_df = df_clean[df_clean["Art_clean"] != ""]
            if has_uk:
                df_uk = art_df.copy()
                df_uk["uk_size_low"] = df_uk["uk_size"].fillna("").astype(str).str.strip().str.lower()
                df_uk = df_uk[df_uk["uk_size_low"] != ""]
                if not df_uk.empty:
                    article_to_uksizes = df_uk.groupby("Art_clean")["uk_size_low"].apply(set).to_dict()
            if has_us:
                df_us = art_df.copy()
                df_us["us_size_low"] = df_us["us_size"].fillna("").astype(str).str.strip().str.lower()
                df_us = df_us[df_us["us_size_low"] != ""]
                if not df_us.empty:
                    article_to_ussizes = df_us.groupby("Art_clean")["us_size_low"].apply(set).to_dict()
            if has_rus:
                df_rus = art_df.copy()
                df_rus["rus_size_low"] = df_rus["rus_size"].fillna("").astype(str).str.strip().str.lower()
                df_rus = df_rus[df_rus["rus_size_low"] != ""]
                if not df_rus.empty:
                    article_to_russizes = df_rus.groupby("Art_clean")["rus_size_low"].apply(set).to_dict()
                    
    return (
        sku_to_article, sku_to_uksize, sku_to_ussize, sku_to_russize, sku_to_gender, sku_to_colorname,
        article_to_uksizes, article_to_ussizes, article_to_russizes
    )


def build_zecom_maps(zecom_df: pd.DataFrame, channel: str) -> Tuple[Dict, Dict, Dict]:
    """
    Builds lookup tables from zEcom File.
    Optimised using vectorised pandas operations for speed.
    """
    article_to_launchdate = {}
    article_to_ecomstatus = {}
    article_to_rrpprice = {}
    
    if zecom_df is not None and not zecom_df.empty:
        platform = channel.split()[0].lower()
        if platform == "tiktok":
            ecom_col = "Ecom_TikTok"
        else:
            ecom_col = f"Ecom_{platform.capitalize()}"
        
        df_clean = zecom_df.copy()
        if "Article No" in df_clean.columns:
            df_clean["Art_clean"] = df_clean["Article No"].apply(_normalise_article_no)
        else:
            df_clean["Art_clean"] = ""
            
        df_clean = df_clean[df_clean["Art_clean"] != ""]
        
        if not df_clean.empty:
            if "Launch Date" in df_clean.columns:
                dates = pd.to_datetime(df_clean["Launch Date"], errors="coerce")
                formatted_dates = dates.dt.date.astype(str).replace("NaT", "")
                article_to_launchdate = dict(zip(df_clean["Art_clean"], formatted_dates))
                
            if ecom_col in df_clean.columns:
                article_to_ecomstatus = dict(zip(df_clean["Art_clean"], df_clean[ecom_col].apply(_safe_str)))
                
            if "rrp_price" in df_clean.columns:
                article_to_rrpprice = dict(zip(df_clean["Art_clean"], df_clean["rrp_price"].apply(_safe_str)))
                
    return article_to_launchdate, article_to_ecomstatus, article_to_rrpprice

# ── Row Validation Logic ──────────────────────────────────────────────────────

def validate_row_internal(
    row: pd.Series, 
    idx: int, 
    channel: str,
    content_maps: Tuple = (None, None, None, None, None, None, None, None),
    zecom_maps: Tuple = (None, None, None),
    allowed_genders: List[str] = ALLOWED_GENDERS, 
    allowed_statuses: List[str] = ALLOWED_STATUSES
) -> List[Dict]:
    """
    Validates a single row for Internal QC with reference lookups, US/Rus size checks, and RRP price checks.
    """
    exceptions = []
    source_file = row.get("_source_file", "Unknown File")
    row_num = row.get("_original_row_number", idx + 2)
    art_num = clean_str(row.get("article_number", ""))
    norm_art = row.get("_norm_art") if "_norm_art" in row else _normalise_article_no(art_num)
    sku_val = row.get("_cleaned_sku") if "_cleaned_sku" in row else _clean_sku(row.get("sku", ""))
    prod_name = clean_str(row.get("product_name", ""))
    gender = clean_str(row.get("gender", ""))
    ecom_status = clean_str(row.get("ecommerce_status", ""))
    
    # ── 1. Apply Size Corrections ──
    raw_size = clean_str(row.get("size", ""))
    size = row.get("_corrected_size") if "_corrected_size" in row else correct_size(raw_size)
    
    sku_to_article, sku_to_uksize, sku_to_ussize, sku_to_russize, sku_to_gender, sku_to_colorname, \
        article_to_uksizes, article_to_ussizes, article_to_russizes = content_maps
        
    article_to_launchdate, article_to_ecomstatus, article_to_rrpprice = zecom_maps

    # Detect Parent SKU (Seller SKU that is not empty and not 13 digits)
    is_parent_sku = False
    if not is_empty(row.get("sku")):
        is_parent_sku = not bool(re.fullmatch(r'\d{13}', sku_val))

    def add_exc(field: str, val, severity: str, msg: str):
        exceptions.append({
            "Source File": source_file,
            "Row Number": row_num,
            "Article Number": art_num if art_num else "MISSING",
            "Product Name": prod_name if prod_name else "MISSING",
            "Field": field,
            "Value": str(val) if not pd.isna(val) else "MISSING",
            "Severity": severity,
            "Message": msg
        })

    # 1. Article Number Basic Check
    if not is_parent_sku and is_empty(row.get("article_number")):
        add_exc("Article Number", row.get("article_number"), "Error", "Article Number is missing.")

    # 2. SKU Basic Check
    if is_empty(row.get("sku")):
        add_exc("SKU", row.get("sku"), "Error", "SKU (EAN) is missing.")
    else:
        if not is_parent_sku and not re.fullmatch(r'\d{13}', sku_val):
            add_exc("SKU", sku_val, "Warning", "SKU must be exactly 13 digits barcode.")

    if not is_parent_sku:
        # 3. E-commerce Status zEcom Check
        ref_ecom_status = "Not Found"
        if article_to_ecomstatus is not None and norm_art:
            ref_ecom_status = article_to_ecomstatus.get(norm_art, "Not Found")
        
        if ref_ecom_status == "Not Found":
            add_exc("Article Number", art_num, "Error", f"Article No '{art_num}' not found in zEcom File lookup.")
        elif _normalise_status(ref_ecom_status) != "Yes":
            add_exc("E-commerce Status", ref_ecom_status, "Error", f"Listing blocked: zEcom File status for this channel is '{ref_ecom_status}' (Should be Yes).")

        # If status is mapped in sheet, compare it
        if pd.notna(row.get("ecommerce_status")) and not is_empty(row.get("ecommerce_status")):
            norm_up_status = _normalise_status(ecom_status)
            if ref_ecom_status != "Not Found" and norm_up_status != _normalise_status(ref_ecom_status):
                add_exc("E-commerce Status", ecom_status, "Error", f"Status mismatch: Uploaded status is '{ecom_status}' but zEcom File defines it as '{ref_ecom_status}' for Article No '{art_num}'.")

    # 4. Launch Date zEcom Check
    if not is_parent_sku and not is_empty(row.get("article_number")):
        ref_ld_str = ""
        ref_ld = None
        if article_to_launchdate is not None and norm_art:
            ref_ld_str = article_to_launchdate.get(norm_art, "")
            if ref_ld_str:
                try:
                    ref_ld = pd.to_datetime(ref_ld_str).date()
                    if ref_ld > datetime.date.today():
                        add_exc("Launch Date", ref_ld_str, "Error", f"Future Launch Date: zEcom File defines launch date as '{ref_ld_str}' (future). Product cannot be listed yet.")
                except Exception:
                    pass

        # If launch date is mapped in sheet, check it
        parsed_date = None
        if pd.notna(row.get("launch_date")) and not is_empty(row.get("launch_date")):
            launch_date_raw = row.get("launch_date")
            if isinstance(launch_date_raw, (datetime.datetime, datetime.date)):
                parsed_date = launch_date_raw
            else:
                for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
                    try:
                        parsed_date = datetime.datetime.strptime(str(launch_date_raw).strip(), fmt).date()
                        break
                    except ValueError:
                        continue
                if parsed_date is None:
                    try:
                        parsed_date = pd.to_datetime(launch_date_raw).date()
                    except Exception:
                        pass
            if parsed_date is None:
                add_exc("Launch Date", launch_date_raw, "Error", "Launch Date has an invalid format. Recommended: YYYY-MM-DD.")
            else:
                if isinstance(parsed_date, datetime.datetime):
                    parsed_date = parsed_date.date()
                if parsed_date > datetime.date.today():
                    add_exc("Launch Date", launch_date_raw, "Error", f"Future Launch Date: Uploaded launch date '{launch_date_raw}' is in the future.")
                if ref_ld and parsed_date != ref_ld:
                    add_exc("Launch Date", launch_date_raw, "Warning", f"Launch Date mismatch: Uploaded '{launch_date_raw}' does not match zEcom File Launch Date '{ref_ld_str}'.")

    if not is_parent_sku:
        # 5. Gender Check
        ref_gender = ""
        if sku_to_gender is not None and sku_val:
            ref_gender = sku_to_gender.get(sku_val, "")
            
        if pd.notna(row.get("gender")) and not is_empty(row.get("gender")):
            if gender.lower() not in [g.lower() for g in allowed_genders]:
                add_exc("Gender", gender, "Error", f"Gender '{gender}' is invalid. Allowed: {', '.join(allowed_genders)}.")
            elif ref_gender and not genders_are_compatible(gender, ref_gender):
                add_exc("Gender", gender, "Warning", f"Gender mismatch: Uploaded gender '{gender}' does not match Content File gender '{ref_gender}' for SKU '{sku_val}'.")

        # Product Name vs Gender Keyword Check using ref_gender (or uploaded gender as fallback)
        gender_for_name_check = ref_gender if ref_gender else gender
        if gender_for_name_check and not is_empty(prod_name):
            gender_low = gender_for_name_check.lower()
            prod_name_low = prod_name.lower()
            
            male_mismatch_keywords = [
                r"\bwomen\b", r"\bwomens\b", r"\bgirl\b", r"\bgirls\b", r"\blady\b", 
                r"\bladies\b", r"\bshe\b", r"\bher\b", r"\bfemale\b", r"\bwoman\b"
            ]
            female_mismatch_keywords = [
                r"\bmen\b", r"\bmens\b", r"\bboy\b", r"\bboys\b", r"\bhim\b", r"\bhis\b", r"\bmale\b"
            ]
            
            if gender_low in ["men", "boys", "male"]:
                for pattern in male_mismatch_keywords:
                    if re.search(pattern, prod_name_low):
                        add_exc("Product Name", prod_name, "Error", f"Gender mismatch: Name contains female keyword '{re.sub(r'[^a-zA-Z]', '', pattern)}' but Gender is '{gender_for_name_check}'.")
                        break
            elif gender_low in ["women", "girls", "female"]:
                for pattern in female_mismatch_keywords:
                    if re.search(pattern, prod_name_low):
                        add_exc("Product Name", prod_name, "Error", f"Gender mismatch: Name contains male keyword '{re.sub(r'[^a-zA-Z]', '', pattern)}' but Gender is '{gender_for_name_check}'.")
                        break

        # 7. Color Name Basic Check
        if is_empty(row.get("color_name")):
            add_exc("Color Name", row.get("color_name"), "Error", "Color Name is missing.")

        # 8. Size Basic Check
        if is_empty(row.get("size")):
            add_exc("Size", row.get("size"), "Error", "Size is missing.")

        # 9. Quantity Check: Must be exactly 0 for target sheet (if not is_live_report), otherwise just must be numeric
        qty_raw = row.get("quantity")
        is_live_report = row.get("_is_live_report", False)
        if is_empty(qty_raw):
            add_exc("Quantity", qty_raw, "Error", "Quantity is missing.")
        else:
            try:
                qty = float(qty_raw)
                if not is_live_report and qty != 0:
                    add_exc("Quantity", qty_raw, "Error", f"Quantity must be exactly 0 (Uploaded: {qty_raw}).")
            except (ValueError, TypeError):
                add_exc("Quantity", qty_raw, "Error", "Quantity is not a valid number.")

        # 10. Price Check & RRP zEcom Comparison
        price_raw = row.get("price")
        if is_empty(price_raw):
            add_exc("Price", price_raw, "Error", "Price is missing.")
        else:
            try:
                price = float(price_raw)
                if price <= 0:
                    add_exc("Price", price_raw, "Error", "Price must be greater than zero.")
                
                # Compare against zEcom RRP Price
                ref_rrp = article_to_rrpprice.get(norm_art, "") if norm_art else ""
                if ref_rrp:
                    try:
                        ref_p_f = float(re.sub(r'[^\d\.]', '', str(ref_rrp)))
                        if not np.isclose(price, ref_p_f):
                            add_exc("Price", price_raw, "Error", f"Price mismatch: Uploaded price '{price_raw}' does not match RRP Price '{ref_rrp}' from zEcom File for Article No '{art_num}'.")
                    except Exception:
                        pass
            except (ValueError, TypeError):
                add_exc("Price", price_raw, "Error", "Price is not a valid number.")

        # ── TikTok MY Malay Language Validation ──
        if "TikTok" in channel:
            title_desc_combined = prod_name.lower()
            has_malay = any(re.search(pat, title_desc_combined) for pat in MALAY_KEYWORDS)
            if not has_malay:
                add_exc("Product Name", prod_name, "Warning", "TikTok Listing: Title/Description should contain Malay language words (e.g. untuk, lelaki, wanita, kasut, saiz).")

        # ── Reference File Cross-Validation Logic ──
        if sku_to_article is not None:
            if sku_val:
                if sku_val in sku_to_article:
                    ref_art = sku_to_article[sku_val]
                    if norm_art and norm_art != ref_art:
                        add_exc("Article Number", art_num, "Error", f"Article mismatch: Uploaded Article No '{art_num}' does not match Content File Article No '{ref_art}' for SKU '{sku_val}'.")
                    
                    # Check Article Number in Product Name
                    if ref_art.lower() not in prod_name.lower():
                        add_exc("Product Name", prod_name, "Error", f"Product Name mismatch: Product Name does not contain Article Number '{ref_art}' from Content File.")
                        
                    # Check Gender in Product Name
                    if sku_to_gender and sku_val in sku_to_gender:
                        ref_gender_local = sku_to_gender[sku_val]
                        if ref_gender_local:
                            gender_low = ref_gender_local.lower().strip()
                            gender_syns = {
                                "men": ["men", "mens", "male", "gentleman", "gentlemen", "boy", "boys"],
                                "male": ["men", "mens", "male", "gentleman", "gentlemen", "boy", "boys"],
                                "women": ["women", "womens", "female", "lady", "ladies", "woman", "girl", "girls"],
                                "female": ["women", "womens", "female", "lady", "ladies", "woman", "girl", "girls"],
                                "unisex": ["unisex", "men", "women", "mens", "womens", "adult", "unisexual", "male", "female"],
                                "kids": ["kids", "boys", "girls", "kid", "boy", "girl", "child", "children", "youth", "toddler"],
                                "boys": ["boys", "boy", "kids", "kid", "child", "children", "youth", "men", "mens", "male"],
                                "girls": ["girls", "girl", "kids", "kid", "child", "children", "youth", "women", "womens", "female"]
                            }
                            syns = gender_syns.get(gender_low, [gender_low])
                            prod_name_low = prod_name.lower()
                            if not any(re.search(r'\b' + re.escape(syn) + r'\b', prod_name_low) for syn in syns) and not any(syn in prod_name_low for syn in syns):
                                add_exc("Product Name", prod_name, "Warning", f"Product Name mismatch: Product Name does not contain reference to gender '{ref_gender_local}' or its synonyms.")

                    # Check Color Name matching
                    if sku_to_colorname and sku_val in sku_to_colorname:
                        ref_color = sku_to_colorname[sku_val]
                        if ref_color:
                            color_name = clean_str(row.get("color_name", ""))
                            if "shopee" in channel.lower():
                                if len(color_name) > 20:
                                    add_exc("Color Name", color_name, "Warning", f"Color Name '{color_name}' exceeds Shopee's 20-character limit.")
                                if color_name.strip().lower() != ref_color[:20].strip().lower():
                                    add_exc("Color Name", color_name, "Error", f"Color Name mismatch: Uploaded Color Name '{color_name}' does not match Content File Color Name '{ref_color}' (Shopee 20-char limit applied: '{ref_color[:20]}').")
                            else:
                                if color_name.strip().lower() != ref_color.strip().lower():
                                    add_exc("Color Name", color_name, "Error", f"Color Name mismatch: Uploaded Color Name '{color_name}' does not match Content File Color Name '{ref_color}'.")

                    # Size Checkup dynamic logic
                    if size:
                        ref_size = ""
                        size_type = "UK size"
                        valid_sizes_for_art = set()
                        
                        if channel == "Lazada PH" and is_footwear(prod_name):
                            ref_size = sku_to_ussize.get(sku_val, "")
                            size_type = "US size"
                            valid_sizes_for_art = article_to_ussizes.get(norm_art, set())
                        elif channel in ["Zalora SG", "Zalora MY", "Zalora PH"] and is_kids_apparel(gender_for_name_check, prod_name):
                            ref_size = sku_to_russize.get(sku_val, "")
                            size_type = "Rus size"
                            valid_sizes_for_art = article_to_russizes.get(norm_art, set())
                        else:
                            ref_size = sku_to_uksize.get(sku_val, "")
                            size_type = "UK size"
                            valid_sizes_for_art = article_to_uksizes.get(norm_art, set())
                            
                        # Fallback to UK size if preferred type is not mapped/empty
                        if not ref_size and (channel == "Lazada PH" or is_kids_apparel(gender_for_name_check, prod_name)):
                            ref_size = sku_to_uksize.get(sku_val, "")
                            size_type = "UK size (Fallback)"
                            valid_sizes_for_art = article_to_uksizes.get(norm_art, set())
                            
                        if ref_size:
                            if clean_size_for_comparison(size) != clean_size_for_comparison(ref_size):
                                add_exc("Size", raw_size, "Error", f"Size mismatch: Size '{raw_size}' (Normalized: '{size}') does not match reference {size_type} '{ref_size}' in Content File for SKU '{sku_val}'.")
                        else:
                            add_exc("Size", raw_size, "Warning", f"No {size_type} mapped in Content File for SKU '{sku_val}'.")
                else:
                    add_exc("SKU", sku_val, "Warning", f"SKU '{sku_val}' not found in Content File lookup.")
                    # Fallback size checking using Article No
                    if norm_art and size:
                        valid_sizes = set()
                        size_type = "UK size"
                        if channel == "Lazada PH" and is_footwear(prod_name):
                            valid_sizes = article_to_ussizes.get(norm_art, set())
                            size_type = "US size"
                        elif channel in ["Zalora SG", "Zalora MY", "Zalora PH"] and is_kids_apparel(gender_for_name_check, prod_name):
                            valid_sizes = article_to_russizes.get(norm_art, set())
                            size_type = "Rus size"
                        else:
                            valid_sizes = article_to_uksizes.get(norm_art, set())
                            size_type = "UK size"
                            
                        if not valid_sizes:
                            valid_sizes = article_to_uksizes.get(norm_art, set())
                            size_type = "UK size (Fallback)"
                            
                        if valid_sizes and clean_size_for_comparison(size) not in [clean_size_for_comparison(vs) for vs in valid_sizes]:
                            add_exc("Size", raw_size, "Error", f"Size mismatch: Size '{raw_size}' (Normalized: '{size}') is not in the list of valid {size_type}s ({', '.join(sorted(list(valid_sizes)))}) in Content File for Article No '{art_num}'.")
            else:
                # Check size by Article No alone if SKU is missing
                if norm_art and size:
                    valid_sizes = set()
                    size_type = "UK size"
                    if channel == "Lazada PH" and is_footwear(prod_name):
                        valid_sizes = article_to_ussizes.get(norm_art, set())
                        size_type = "US size"
                    elif channel in ["Zalora SG", "Zalora MY", "Zalora PH"] and is_kids_apparel(gender_for_name_check, prod_name):
                        valid_sizes = article_to_russizes.get(norm_art, set())
                        size_type = "Rus size"
                    else:
                        valid_sizes = article_to_uksizes.get(norm_art, set())
                        size_type = "UK size"
                        
                    if not valid_sizes:
                        valid_sizes = article_to_uksizes.get(norm_art, set())
                        size_type = "UK size (Fallback)"
                        
                    if valid_sizes and clean_size_for_comparison(size) not in [clean_size_for_comparison(vs) for vs in valid_sizes]:
                        add_exc("Size", raw_size, "Error", f"Size mismatch: Size '{raw_size}' (Normalized: '{size}') is not in the list of valid {size_type}s ({', '.join(sorted(list(valid_sizes)))}) in Content File for Article No '{art_num}'.")

    return exceptions


_IMAGE_URL_CACHE = {}

def check_live_image_url(url: str) -> Tuple[bool, str]:
    if url in _IMAGE_URL_CACHE:
        return _IMAGE_URL_CACHE[url]
    try:
        resp = requests.head(url, timeout=2)
        if resp.status_code < 400:
            result = (True, "")
        else:
            resp_get = requests.get(url, timeout=2, stream=True)
            if resp_get.status_code < 400:
                result = (True, "")
            else:
                result = (False, f"broken (HTTP Status {resp_get.status_code})")
    except Exception as e:
        result = (False, f"unreachable: {type(e).__name__}")
    _IMAGE_URL_CACHE[url] = result
    return result

def validate_row_post(
    row: pd.Series, 
    idx: int, 
    channel: str,
    content_maps: Tuple = (None, None, None, None, None, None, None, None),
    zecom_maps: Tuple = (None, None, None),
    check_live_images: bool = False, 
    allowed_genders: List[str] = ALLOWED_GENDERS, 
    allowed_statuses: List[str] = ALLOWED_STATUSES
) -> List[Dict]:
    """
    Validates a single row for Post QC.
    Inherits Internal QC checks, then checks Images and Size Chart columns.
    """
    exceptions = validate_row_internal(row, idx, channel, content_maps, zecom_maps, allowed_genders, allowed_statuses)
    
    sku_val = row.get("_cleaned_sku") if "_cleaned_sku" in row else _clean_sku(row.get("sku", ""))
    is_parent_sku = False
    if not is_empty(row.get("sku")):
        is_parent_sku = not bool(re.fullmatch(r'\d{13}', sku_val))
        
    if is_parent_sku:
        return exceptions
        
    source_file = row.get("_source_file", "Unknown File")
    row_num = row.get("_original_row_number", idx + 2)
    art_num = clean_str(row.get("article_number", ""))
    prod_name = clean_str(row.get("product_name", ""))
    gender = clean_str(row.get("gender", ""))

    def add_exc(field: str, val, severity: str, msg: str):
        exceptions.append({
            "Source File": source_file,
            "Row Number": row_num,
            "Article Number": art_num if art_num else "MISSING",
            "Product Name": prod_name if prod_name else "MISSING",
            "Field": field,
            "Value": str(val) if not pd.isna(val) else "MISSING",
            "Severity": severity,
            "Message": msg
        })

    # 1. Images
    images_raw = row.get("images")
    if is_empty(images_raw):
        add_exc("Images", images_raw, "Error", "Images column is missing or empty.")
    else:
        img_urls = [url.strip() for url in re.split(r'[,;\n]+', str(images_raw)) if url.strip()]
        if not img_urls:
            add_exc("Images", images_raw, "Error", "No valid image links found.")
        else:
            for i, url in enumerate(img_urls):
                if not URL_REGEX.match(url):
                    add_exc("Images", url, "Error", f"Image #{i+1} is not a valid URL format.")
                elif check_live_images:
                    ok, err_msg = check_live_image_url(url)
                    if not ok:
                        add_exc("Images", url, "Error", f"Image #{i+1} link is {err_msg}.")

    # 2. Size Chart
    size_chart_raw = row.get("size_chart")
    if is_empty(size_chart_raw):
        add_exc("Size Chart", size_chart_raw, "Error", "Size Chart attachment is missing.")
    else:
        size_chart = str(size_chart_raw).strip()
        if "http" in size_chart.lower() and not URL_REGEX.match(size_chart):
            add_exc("Size Chart", size_chart, "Warning", "Size Chart link is invalid URL format.")
        
        if not is_empty(gender):
            sc_low = size_chart.lower()
            g_low = gender.lower()
            if g_low in ["men", "boys"] and any(w in sc_low for w in ["women", "womens", "girl", "girls", "lady"]):
                add_exc("Size Chart", size_chart, "Warning", f"Size Chart reference seems to belong to females ('{size_chart}') but product gender is '{gender}'.")
            elif g_low in ["women", "girls"]:
                has_men_only = re.search(r"\bmen\b|\bmens\b|\bboy\b|\bboys\b", sc_low)
                if has_men_only:
                    add_exc("Size Chart", size_chart, "Warning", f"Size Chart reference seems to belong to males ('{size_chart}') but product gender is '{gender}'.")

    return exceptions


def validate_dataframe(
    df: pd.DataFrame, 
    qc_stage: str = "Internal QC",
    channel: str = "Lazada PH",
    content_df: pd.DataFrame = None,
    zecom_df: pd.DataFrame = None,
    check_live_images: bool = False, 
    allowed_genders: List[str] = ALLOWED_GENDERS, 
    allowed_statuses: List[str] = ALLOWED_STATUSES,
    is_live_report: bool = False
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str]]:
    """
    Validates a whole standardized DataFrame with UK, US, Russian size and zEcom RRP rules.
    """
    df = df.copy()
    df["_is_live_report"] = is_live_report
    logs = []
    logs.append(f"Starting validation run at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logs.append(f"Validation Stage: {qc_stage} | Target Channel: {channel}")
    logs.append(f"Dataset contains {len(df)} records.")
    
    content_maps = build_content_maps(content_df)
    logs.append("Content File size mappings built successfully.")
    zecom_maps = build_zecom_maps(zecom_df, channel)
    logs.append(f"zEcom File status and RRP price mappings built successfully.")
    if zecom_df is not None and hasattr(zecom_df, "attrs") and "selected_sheet" in zecom_df.attrs:
        logs.append(f"Loaded zEcom sheet '{zecom_df.attrs['selected_sheet']}' (available: {zecom_df.attrs['sheet_names']}) for country '{zecom_df.attrs['passed_country']}'.")
    
    sku_to_article = content_maps[0] if content_maps else None
        
    all_exceptions = []
    
    errors_col = []
    warnings_col = []
    status_col = []
    details_col = []
    
    zecom_status_col = []
    gender_check_col = []
    color_check_col = []
    size_check_col = []
    rrp_check_col = []
    ref_color_name_col = []
    ref_size_col = []
    ref_rrp_col = []
    
    # ── Pre-calculate and clean columns vectorially ──
    df["_cleaned_sku"] = df["sku"].fillna("").astype(str).str.strip().apply(_clean_sku)
    df["_norm_art"] = df["article_number"].fillna("").astype(str).str.strip().apply(_normalise_article_no)
    df["_corrected_size"] = df["size"].fillna("").astype(str).str.strip().apply(correct_size)
    df["_corrected_size_low"] = df["_corrected_size"].str.lower().str.strip()
    
    # Resolve missing Article Number using SKU from content_maps
    if sku_to_article:
        missing_art_mask = df["article_number"].fillna("").astype(str).str.strip() == ""
        resolved_arts = df.loc[missing_art_mask, "_cleaned_sku"].map(sku_to_article)
        df.loc[missing_art_mask, "article_number"] = resolved_arts.fillna("")
        df.loc[missing_art_mask, "_norm_art"] = df.loc[missing_art_mask, "article_number"].apply(_normalise_article_no)

    # Resolve missing Launch Date using _norm_art from zecom_maps
    if zecom_maps:
        article_to_launchdate, _, _ = zecom_maps
        if article_to_launchdate:
            missing_launch_mask = df["launch_date"].fillna("").astype(str).str.strip() == ""
            resolved_launches = df.loc[missing_launch_mask, "_norm_art"].map(article_to_launchdate)
            df.loc[missing_launch_mask, "launch_date"] = resolved_launches.fillna("")

    # Resolve missing Gender using SKU from content_maps
    if content_maps:
        sku_to_gender = content_maps[4]
        if sku_to_gender:
            missing_gender_mask = df["gender"].fillna("").astype(str).str.strip() == ""
            resolved_genders = df.loc[missing_gender_mask, "_cleaned_sku"].map(sku_to_gender)
            df.loc[missing_gender_mask, "gender"] = resolved_genders.fillna("")
            
    # Group by SKU and Size (after applying corrections) to find duplicates (only for 13-digit SKUs)
    duplicate_skus_sizes = set()
    if "sku" in df.columns and "size" in df.columns:
        is_13 = df["_cleaned_sku"].str.match(r'^\d{13}$')
        dup_mask = df.duplicated(subset=["_cleaned_sku", "_corrected_size_low"], keep=False) & is_13
        dups = df[dup_mask]
        if not dups.empty:
            duplicate_skus_sizes = set(zip(dups["_cleaned_sku"], dups["_corrected_size_low"]))
                
    logs.append(f"Found {len(duplicate_skus_sizes)} duplicate 13-digit sku+size combinations in upload sheet.")

    for idx, row in df.iterrows():
        sku_val = row["_cleaned_sku"]
        art_num = clean_str(row.get("article_number", ""))
        is_parent_sku = False
        if sku_val:
            is_parent_sku = not bool(re.fullmatch(r'\d{13}', sku_val))

        if qc_stage == "Internal QC":
            row_exceptions = validate_row_internal(row, idx, channel, content_maps, zecom_maps, allowed_genders, allowed_statuses)
        else:
            row_exceptions = validate_row_post(row, idx, channel, content_maps, zecom_maps, check_live_images, allowed_genders, allowed_statuses)
            
        sk = sku_val
        raw_size = clean_str(row.get("size", ""))
        sz_corrected = correct_size(raw_size).strip().lower()
        
        if (sk, sz_corrected) in duplicate_skus_sizes:
            row_exceptions.append({
                "Source File": row.get("_source_file", "Unknown File"),
                "Row Number": row.get("_original_row_number", idx + 2),
                "Article Number": clean_str(row.get("article_number", "")),
                "Product Name": clean_str(row.get("product_name", "")),
                "Field": "SKU & Size",
                "Value": f"SKU: {sk}, Size: {raw_size}",
                "Severity": "Warning",
                "Message": f"Duplicate record: product with SKU '{sk}' and corrected size '{correct_size(raw_size)}' is uploaded multiple times."
            })
            
        row_errors = sum(1 for e in row_exceptions if e["Severity"] == "Error")
        row_warnings = sum(1 for e in row_exceptions if e["Severity"] == "Warning")
        
        errors_col.append(row_errors)
        warnings_col.append(row_warnings)
        
        if row_errors > 0:
            status_col.append("Failed")
        elif row_warnings > 0:
            status_col.append("Warning")
        else:
            status_col.append("Passed")
            
        details_col.append("; ".join([f"{e['Field']}: {e['Message']}" for e in row_exceptions]))
        all_exceptions.extend(row_exceptions)
        
        # ── Populate Check Columns ──
        norm_art = _normalise_article_no(art_num)
        
        # zEcom Status lookup
        ref_ecom_status = "Not Found"
        if is_parent_sku:
            ref_ecom_status = "" # Not fetched (blank) for Parent SKUs
        elif zecom_maps:
            article_to_launchdate, article_to_ecomstatus, article_to_rrpprice = zecom_maps
            if article_to_ecomstatus and norm_art:
                ref_ecom_status = article_to_ecomstatus.get(norm_art, "Not Found")
        zecom_status_col.append(ref_ecom_status)
        
        # Filter row exceptions for checks
        gender_msgs = []
        color_msgs = []
        size_msgs = []
        rrp_msgs = []
        
        for exc in row_exceptions:
            field = exc.get("Field", "")
            msg = exc.get("Message", "")
            
            if field == "Gender":
                gender_msgs.append(msg)
            elif field == "Product Name" and "gender" in msg.lower():
                gender_msgs.append(msg)
            elif field == "Color Name":
                color_msgs.append(msg)
            elif field == "Size":
                size_msgs.append(msg)
            elif field == "Price":
                rrp_msgs.append(msg)
                
        gender_check_col.append("; ".join(gender_msgs) if gender_msgs else "OK")
        color_check_col.append("; ".join(color_msgs) if color_msgs else "OK")
        size_check_col.append("; ".join(size_msgs) if size_msgs else "OK")
        rrp_check_col.append("; ".join(rrp_msgs) if rrp_msgs else "OK")
        
        # Determine Reference values for display
        ref_color_val = ""
        ref_size_val = ""
        ref_rrp_val = ""
        
        if not is_parent_sku:
            if content_maps:
                sku_to_article, sku_to_uksize, sku_to_ussize, sku_to_russize, sku_to_gender, sku_to_colorname, \
                    article_to_uksizes, article_to_ussizes, article_to_russizes = content_maps
                
                if sku_val in sku_to_colorname:
                    ref_color_val = sku_to_colorname[sku_val]
                    
                if sku_val in sku_to_article:
                    if channel == "Lazada PH" and is_footwear(row.get("product_name", "")):
                        ref_size_val = sku_to_ussize.get(sku_val, "")
                    elif channel in ["Zalora SG", "Zalora MY", "Zalora PH"] and is_kids_apparel(row.get("gender", ""), row.get("product_name", "")):
                        ref_size_val = sku_to_russize.get(sku_val, "")
                    else:
                        ref_size_val = sku_to_uksize.get(sku_val, "")
                    
                    if not ref_size_val:
                        ref_size_val = sku_to_uksize.get(sku_val, "")
                else:
                    if norm_art:
                        valid_sizes = set()
                        if channel == "Lazada PH" and is_footwear(row.get("product_name", "")):
                            valid_sizes = article_to_ussizes.get(norm_art, set())
                        elif channel in ["Zalora SG", "Zalora MY", "Zalora PH"] and is_kids_apparel(row.get("gender", ""), row.get("product_name", "")):
                            valid_sizes = article_to_russizes.get(norm_art, set())
                        else:
                            valid_sizes = article_to_uksizes.get(norm_art, set())
                        if not valid_sizes:
                            valid_sizes = article_to_uksizes.get(norm_art, set())
                        if valid_sizes:
                            ref_size_val = ", ".join(sorted(list(valid_sizes)))
                            
            if zecom_maps and norm_art:
                _, _, article_to_rrpprice = zecom_maps
                if article_to_rrpprice and norm_art in article_to_rrpprice:
                    ref_rrp_val = article_to_rrpprice[norm_art]
                    
        ref_color_name_col.append(ref_color_val)
        ref_size_col.append(ref_size_val)
        ref_rrp_col.append(ref_rrp_val)
        
    val_df = df.copy()
    val_df["_qc_status"] = status_col
    val_df["_qc_errors"] = errors_col
    val_df["_qc_warnings"] = warnings_col
    val_df["_qc_details"] = details_col
    
    val_df["Zeocm Status"] = zecom_status_col
    val_df["Gender Check"] = gender_check_col
    val_df["ref_color_name"] = ref_color_name_col
    val_df["Color Check"] = color_check_col
    val_df["ref_size"] = ref_size_col
    val_df["Size Check"] = size_check_col
    val_df["ref_rrp"] = ref_rrp_col
    val_df["RRP Check"] = rrp_check_col
    
    if all_exceptions:
        exc_df = pd.DataFrame(all_exceptions)
    else:
        exc_df = pd.DataFrame(columns=["Source File", "Row Number", "Article Number", "Product Name", "Field", "Value", "Severity", "Message"])
        
    logs.append(f"Validation completed. Passed: {status_col.count('Passed')}, Warnings: {status_col.count('Warning')}, Failed: {status_col.count('Failed')}")
    
    return exc_df, val_df, logs


def compare_source_and_live(
    source_df: pd.DataFrame, 
    live_df: pd.DataFrame, 
    match_column: str = "sku",
    content_df: pd.DataFrame = None,
    zecom_df: pd.DataFrame = None,
    channel: str = None
) -> Tuple[pd.DataFrame, Dict]:
    """
    Compares Standardized Source Data against Standardized Live Data.
    And executes all 9 checks against reference databases.
    """
    comparison_records = []
    
    src_clean = source_df.copy()
    src_clean[match_column] = src_clean[match_column].astype(str).str.strip().apply(_clean_sku)
    src_clean = src_clean[src_clean[match_column] != ""]
    
    live_clean = live_df.copy()
    live_clean[match_column] = live_clean[match_column].astype(str).str.strip().apply(_clean_sku)
    live_clean = live_clean[live_clean[match_column] != ""]
    
    composite_match = "size" in src_clean.columns and "size" in live_clean.columns
    
    if composite_match:
        src_clean["_match_key"] = src_clean[match_column] + " | " + src_clean["size"].astype(str).str.strip().apply(correct_size).str.lower()
        live_clean["_match_key"] = live_clean[match_column] + " | " + live_clean["size"].astype(str).str.strip().apply(correct_size).str.lower()
        key_col = "_match_key"
    else:
        key_col = match_column
        
    # Deduplicate match keys to make dict conversion unique
    src_clean = src_clean.drop_duplicates(subset=[key_col])
    live_clean = live_clean.drop_duplicates(subset=[key_col])
    
    # Convert to dict of records keyed by key_col for high performance lookup
    src_dict = src_clean.set_index(key_col).to_dict('index')
    live_dict = live_clean.set_index(key_col).to_dict('index')
    
    # Run 9 checks on live listings first
    live_val_dict = {}
    if content_df is not None and zecom_df is not None and channel is not None:
        # Map live_clean columns to standard validation columns
        live_std = pd.DataFrame()
        live_std["sku"] = live_clean[match_column]
        live_std["article_number"] = ""
        live_std["launch_date"] = ""
        live_std["gender"] = ""
        live_std["product_name"] = live_clean["product_name"] if "product_name" in live_clean.columns else ""
        live_std["color_name"] = live_clean["color_name"] if "color_name" in live_clean.columns else ""
        live_std["size"] = live_clean["size"] if "size" in live_clean.columns else ""
        live_std["price"] = live_clean["price"] if "price" in live_clean.columns else "0.0"
        live_std["quantity"] = live_clean["quantity"] if "quantity" in live_clean.columns else "0"
        live_std["images"] = live_clean["images"] if "images" in live_clean.columns else ""
        live_std["size_chart"] = live_clean["size_chart"] if "size_chart" in live_clean.columns else ""
        live_std["ecommerce_status"] = live_clean["ecommerce_status"] if "ecommerce_status" in live_clean.columns else "Active"
        live_std["_source_file"] = "Live Report"
        live_std["_original_row_number"] = range(2, len(live_clean) + 2)
        
        _, live_val_df, _ = validate_dataframe(
            live_std,
            qc_stage="Post QC",
            channel=channel,
            content_df=content_df,
            zecom_df=zecom_df,
            check_live_images=False, # Skip http checks during comparison to stay fast
            is_live_report=True
        )
        
        if composite_match:
            live_val_df["_match_key"] = live_val_df["sku"].astype(str).str.strip().apply(_clean_sku) + " | " + live_val_df["size"].astype(str).str.strip().apply(correct_size).str.lower()
        else:
            live_val_df["_match_key"] = live_val_df["sku"].astype(str).str.strip().apply(_clean_sku)
        live_val_dict = live_val_df.drop_duplicates(subset=["_match_key"]).set_index("_match_key").to_dict('index')
        
    all_keys = set(src_dict.keys()).union(set(live_dict.keys()))
    
    matched_count = 0
    mismatch_count = 0
    missing_in_live = 0
    missing_in_source = 0
    
    fields_to_compare = ["price", "quantity", "ecommerce_status", "product_name", "color_name", "images", "size_chart"]
    
    for key in all_keys:
        src_row = src_dict.get(key)
        live_row = live_dict.get(key)
        
        # Get 9 reference check results for the live listing
        live_chk = live_val_dict.get(key, {})
        
        # Initialize check statuses
        zec_chk_val = live_chk.get("Zeocm Status", "-")
        ld_chk_val = "-"
        gd_chk_val = live_chk.get("Gender Check", "-")
        col_chk_val = live_chk.get("Color Check", "-")
        sz_chk_val = live_chk.get("Size Check", "-")
        prc_chk_val = live_chk.get("RRP Check", "-")
        
        qc_det = live_chk.get("_qc_details", "")
        if "Launch Date" in qc_det:
            ld_chk_val = "Mismatch"
        elif live_chk:
            ld_chk_val = "OK"
            
        img_chk_val = "-"
        sc_chk_val = "-"
        if live_chk:
            img_chk_val = "Error" if "Images:" in qc_det else "OK"
            sc_chk_val = "Error" if "Size Chart:" in qc_det or "Size chart:" in qc_det else "OK"
        
        if src_row and live_row:
            matched_count += 1
            art_num = src_row.get("article_number", "")
            sz = src_row.get("size", "N/A")
            prod_name = src_row.get("product_name", "")
            
            row_mismatches = []
            
            for field in fields_to_compare:
                src_field = field
                live_field = field
                
                if field == "quantity" and "MP Stock" in live_row:
                    live_field = "MP Stock"
                elif field == "quantity" and "quantity" in live_row:
                    live_field = "quantity"
                    
                if field == "ecommerce_status" and "MP Status" in live_row:
                    live_field = "MP Status"
                elif field == "ecommerce_status" and "ecommerce_status" in live_row:
                    live_field = "ecommerce_status"
                    
                if field == "price" and "MP Price" in live_row:
                    live_field = "MP Price"
                elif field == "price" and "price" in live_row:
                    live_field = "price"
                    
                if field == "product_name" and "MP Product Name" in live_row:
                    live_field = "MP Product Name"
                elif field == "product_name" and "product_name" in live_row:
                    live_field = "product_name"
                    
                s_val = src_row.get(src_field)
                l_val = live_row.get(live_field)
                
                is_diff = False
                if s_val is not None and l_val is not None:
                    if field == "color_name":
                        s_c = str(s_val).strip().lower()
                        l_c = str(l_val).strip().lower()
                        is_diff = (s_c != l_c) and (s_c not in l_c) and (l_c not in s_c) if s_c and l_c else (s_c != l_c)
                    elif field == "ecommerce_status":
                        is_diff = _normalise_status(s_val) != _normalise_status(l_val)
                    elif field in ["price", "quantity"]:
                        try:
                            s_f = float(re.sub(r'[^\d\.]', '', str(s_val))) if s_val else 0.0
                            l_f = float(re.sub(r'[^\d\.]', '', str(l_val))) if l_val else 0.0
                            is_diff = not np.isclose(s_f, l_f)
                        except (ValueError, TypeError):
                            is_diff = str(s_val).strip().lower() != str(l_val).strip().lower()
                    else:
                        is_diff = clean_str(s_val).lower() != clean_str(l_val).lower()
                        
                if is_diff:
                    row_mismatches.append(field)
                    ref_val = "-"
                    if field == "color_name":
                        ref_val = live_chk.get("ref_color_name", "-")
                    elif field == "size":
                        ref_val = live_chk.get("ref_size", "-")
                    elif field == "price":
                        ref_val = live_chk.get("ref_rrp", "-")
                    elif field == "ecommerce_status":
                        ref_val = live_chk.get("Zeocm Status", "-")
                    
                    comparison_records.append({
                        "Article Number": art_num,
                        "Size": sz,
                        "Product Name": prod_name,
                        "Comparison Field": field.replace("_", " ").title(),
                        "Source Value": str(s_val) if s_val is not None else "",
                        "Live Value": str(l_val) if l_val is not None else "",
                        "Reference Value": str(ref_val) if ref_val is not None else "-",
                        "Match Status": "Mismatch",
                        "Description": f"Discrepancy in {field.replace('_', ' ')}. Upload Sheet: {s_val}, Live Store: {l_val}",
                        "zEcom Status Check": zec_chk_val,
                        "Launch Date Check": ld_chk_val,
                        "Gender Check": gd_chk_val,
                        "Color Check": col_chk_val,
                        "Size Check": sz_chk_val,
                        "RRP Check": prc_chk_val,
                        "Images Check": img_chk_val,
                        "Size Chart Check": sc_chk_val
                    })
            
            if row_mismatches:
                mismatch_count += 1
            else:
                comparison_records.append({
                    "Article Number": art_num,
                    "Size": sz,
                    "Product Name": prod_name,
                    "Comparison Field": "All Fields",
                    "Source Value": "-",
                    "Live Value": "-",
                    "Reference Value": "-",
                    "Match Status": "Passed",
                    "Description": "All compared listing attributes match correctly.",
                    "zEcom Status Check": zec_chk_val,
                    "Launch Date Check": ld_chk_val,
                    "Gender Check": gd_chk_val,
                    "Color Check": col_chk_val,
                    "Size Check": sz_chk_val,
                    "RRP Check": prc_chk_val,
                    "Images Check": img_chk_val,
                    "Size Chart Check": sc_chk_val
                })
                
        elif src_row:
            missing_in_live += 1
            comparison_records.append({
                "Article Number": src_row.get("article_number", ""),
                "Size": src_row.get("size", "N/A"),
                "Product Name": src_row.get("product_name", ""),
                "Comparison Field": "Listing Presence",
                "Source Value": "Present",
                "Live Value": "Missing",
                "Reference Value": "-",
                "Match Status": "Failed (Missing Live)",
                "Description": "Product exists in uploaded sheet but is missing from live store listings.",
                "zEcom Status Check": "-",
                "Launch Date Check": "-",
                "Gender Check": "-",
                "Color Check": "-",
                "Size Check": "-",
                "RRP Check": "-",
                "Images Check": "-",
                "Size Chart Check": "-"
            })
        else:
            missing_in_source += 1
            comparison_records.append({
                "Article Number": live_row.get("Article No", live_row.get("article_number", "Unknown")),
                "Size": live_row.get("size", "N/A"),
                "Product Name": live_row.get("product_name", "Unknown"),
                "Comparison Field": "Listing Presence",
                "Source Value": "Missing",
                "Live Value": "Present",
                "Reference Value": "-",
                "Match Status": "Warning (Extra Live)",
                "Description": "Product is live on store but missing from uploaded master sheet.",
                "zEcom Status Check": zec_chk_val,
                "Launch Date Check": ld_chk_val,
                "Gender Check": gd_chk_val,
                "Color Check": col_chk_val,
                "Size Check": sz_chk_val,
                "RRP Check": prc_chk_val,
                "Images Check": img_chk_val,
                "Size Chart Check": sc_chk_val
            })
            
    summary_metrics = {
        "Total SKU variants Analyzed": len(all_keys),
        "Fully Matched Items": matched_count - mismatch_count,
        "Items with Mismatches": mismatch_count,
        "Missing in Live Store": missing_in_live,
        "Extra Live Store Listings": missing_in_source
    }
    
    if comparison_records:
        comp_df = pd.DataFrame(comparison_records)
    else:
        comp_df = pd.DataFrame(columns=[
            "Article Number", "Size", "Product Name", "Comparison Field", "Source Value", "Live Value", "Reference Value",
            "Match Status", "Description", "zEcom Status Check", "Launch Date Check", "Gender Check", 
            "Color Check", "Size Check", "RRP Check", "Images Check", "Size Chart Check"
        ])
        
    return comp_df, summary_metrics
