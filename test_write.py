import pandas as pd
import os
import time

print("Generating 120,456 rows...")
num_rows = 120456
df = pd.DataFrame({
    "Marketplace": ["Shopee PH"] * num_rows,
    "SellerSku": [f"SKU_{i}" for i in range(num_rows)],
    "TC SKU": [f"TC_{i}" for i in range(num_rows)],
    "Product ID": [f"PID_{i}" for i in range(num_rows)]
})

sheets = {"PID Validation": df}
fpath = "test_mem_write.xlsx"

print("Writing sheet with normal xlsxwriter...")
start_time = time.time()
with pd.ExcelWriter(fpath, engine="xlsxwriter") as writer:
    for sheet_name, df_sheet in sheets.items():
        df_sheet.to_excel(writer, sheet_name=sheet_name, index=False)
print(f"Finished writing in {time.time() - start_time:.2f} seconds.")

print("Reading written sheet back...")
df_back = pd.read_excel(fpath, sheet_name="PID Validation")
print(f"Loaded shape: {df_back.shape}")
print("Checking blank rows in columns B to D:")
cols_to_check = ["SellerSku", "TC SKU", "Product ID"]
blank_rows = df_back[df_back[cols_to_check].isna().all(axis=1)]
print(f"Blank rows: {len(blank_rows)}")

# Try to clean up after closing handles
try:
    if os.path.exists(fpath):
        os.remove(fpath)
except Exception:
    pass
