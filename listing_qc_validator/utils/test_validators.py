import unittest
import pandas as pd
import datetime
from listing_qc_validator.utils.validators import (
    validate_row_internal, 
    validate_row_post, 
    validate_dataframe, 
    compare_source_and_live,
    build_content_maps,
    build_zecom_maps,
    correct_size
)

class TestValidators(unittest.TestCase):
    
    def setUp(self):
        # 1. Mock Content Reference File Data with UK, US, and Russian Sizes
        self.mock_content_df = pd.DataFrame([
            {
                "SKU": "4069161482557",
                "Article No": "404620_07",
                "uk_size": "42",
                "us_size": "9",
                "rus_size": "41",
                "content_gender": "Men",
                "content_color_name": "Black"
            },
            {
                "SKU": "4069161482999",
                "Article No": "531103_03",
                "uk_size": "S",
                "us_size": "XS",
                "rus_size": "44",
                "content_gender": "Kids",
                "content_color_name": "Grey"
            }
        ])
        
        # 2. Mock zEcom Reference File Data (with RRP Price column)
        self.mock_zecom_df = pd.DataFrame([
            {
                "Article No": "404620_07",
                "Launch Date": pd.to_datetime("2026-06-20"),
                "Ecom_Shopee": "Yes",
                "Ecom_Lazada": "Yes",
                "Ecom_Zalora": "Yes",
                "rrp_price": "89.99"
            },
            {
                "Article No": "531103_03",
                "Launch Date": pd.to_datetime("2026-06-15"),
                "Ecom_Shopee": "No",
                "Ecom_Lazada": "Yes",
                "Ecom_Zalora": "Yes",
                "rrp_price": "49.99"
            }
        ])
        
        # Build maps
        self.content_maps = build_content_maps(self.mock_content_df)
        self.zecom_maps_shopee = build_zecom_maps(self.mock_zecom_df, "Shopee PH")
        
        # 3. Base Valid Row in Upload Sheet (to be validated)
        self.valid_upload_row = pd.Series({
            "article_number": "404620_07",
            "sku": "4069161482557",
            "ecommerce_status": "Active",
            "launch_date": "2026-06-20",
            "gender": "Men",
            "product_name": "Men's Leather Running Shoes Black Edition (404620_07)",
            "color_name": "Black",
            "size": "42",  # Matches UK size 42 in Content File
            "quantity": 0,   # Must be exactly 0
            "price": 89.99,  # Matches RRP Price 89.99 in zEcom File
            "_original_row_number": 2,
            "_source_file": "test_upload.csv"
        })

    def test_valid_row_cross_reference(self):
        excs = validate_row_internal(
            self.valid_upload_row, 0, 
            channel="Shopee PH",
            content_maps=self.content_maps, 
            zecom_maps=self.zecom_maps_shopee
        )
        self.assertEqual(len(excs), 0, f"Expected 0 exceptions on valid row, found: {excs}")

    def test_quantity_must_be_zero(self):
        row = self.valid_upload_row.copy()
        row["quantity"] = 10  # Invalid, must be 0
        excs = validate_row_internal(
            row, 0, 
            channel="Shopee PH",
            content_maps=self.content_maps, 
            zecom_maps=self.zecom_maps_shopee
        )
        qty_excs = [e for e in excs if e["Field"] == "Quantity"]
        self.assertTrue(len(qty_excs) > 0)
        self.assertIn("must be exactly 0", qty_excs[0]["Message"])

    def test_price_mismatch_against_rrp(self):
        row = self.valid_upload_row.copy()
        row["price"] = 99.99  # Does not match RRP 89.99
        excs = validate_row_internal(
            row, 0, 
            channel="Shopee PH",
            content_maps=self.content_maps, 
            zecom_maps=self.zecom_maps_shopee
        )
        price_excs = [e for e in excs if e["Field"] == "Price"]
        self.assertTrue(len(price_excs) > 0)
        self.assertIn("does not match RRP Price", price_excs[0]["Message"])

    def test_size_corrections(self):
        # 2XL correction to XXL
        self.assertEqual(correct_size("2XL"), "XXL")
        self.assertEqual(correct_size("Youth"), "M")
        self.assertEqual(correct_size("Small"), "S")
        self.assertEqual(correct_size("OSFA"), "One Size")

    def test_lazada_ph_footwear_us_size_rule(self):
        # Lazada PH + Footwear ("Running Shoes") -> US size check (reference US size for SKU is '9')
        row = self.valid_upload_row.copy()
        row["size"] = "9"  # US Size
        zecom_maps_lazada = build_zecom_maps(self.mock_zecom_df, "Lazada PH")
        # Set Ecom Status to Inactive in upload row because Ecom_Lazada is Inactive in mock zEcom
        row["ecommerce_status"] = "Active"
        excs = validate_row_internal(
            row, 0, 
            channel="Lazada PH",
            content_maps=self.content_maps, 
            zecom_maps=zecom_maps_lazada
        )
        self.assertEqual(len(excs), 0, f"Expected US size 9 to pass on Lazada PH Footwear. Found: {excs}")

    def test_zalora_kids_apparel_russian_size_rule(self):
        # Zalora MY + Kids Apparel ("Jogger Pants" - NOT footwear) -> Rus size check (reference Rus size for EAN 4069161482999 is '44')
        row = pd.Series({
            "article_number": "531103_03",
            "sku": "4069161482999",
            "ecommerce_status": "Active", # zEcom Ecom_Shopee is Inactive
            "launch_date": "2026-06-15",
            "gender": "Kids",
            "product_name": "Kids Lightweight Jogger Pants (531103_03)", # Apparel
            "color_name": "Grey",
            "size": "44",  # Matches Russian size 44
            "quantity": 0,
            "price": 49.99,
            "_original_row_number": 3,
            "_source_file": "test_upload.csv"
        })
        zecom_maps_zalora = build_zecom_maps(self.mock_zecom_df, "Zalora MY")
        excs = validate_row_internal(
            row, 0, 
            channel="Zalora MY",
            content_maps=self.content_maps, 
            zecom_maps=zecom_maps_zalora
        )
        # We expect 0 exceptions since size 44 matches the Russian size reference.
        self.assertEqual(len(excs), 0, f"Expected Russian size 44 to pass on Zalora Kids Apparel. Found: {excs}")

    def test_tiktok_my_malay_keyword_warning(self):
        # TikTok MY channel with no Malay words in Title -> expects warning
        row = self.valid_upload_row.copy()
        row["product_name"] = "PUMA Softride Running Shoes"  # English only
        excs = validate_row_internal(
            row, 0, 
            channel="TikTok MY",
            content_maps=self.content_maps, 
            zecom_maps=self.zecom_maps_shopee
        )
        tiktok_excs = [e for e in excs if "TikTok Listing" in e["Message"]]
        self.assertTrue(len(tiktok_excs) > 0)
        self.assertEqual(tiktok_excs[0]["Severity"], "Warning")

        # TikTok MY with Malay word ("kasut") -> expect NO warning
        row["product_name"] = "Kasut Softride Running Shoes"
        excs2 = validate_row_internal(
            row, 0, 
            channel="TikTok MY",
            content_maps=self.content_maps, 
            zecom_maps=self.zecom_maps_shopee
        )
        tiktok_excs2 = [e for e in excs2 if "TikTok Listing" in e["Message"]]
        self.assertEqual(len(tiktok_excs2), 0)

    def test_gender_compatibility(self):
        from listing_qc_validator.utils.validators import genders_are_compatible
        self.assertTrue(genders_are_compatible("Female", "Women"))
        self.assertTrue(genders_are_compatible("women", "female"))
        self.assertTrue(genders_are_compatible("Male", "Men"))
        self.assertTrue(genders_are_compatible("men", "male"))
        self.assertFalse(genders_are_compatible("Male", "Female"))

    def test_size_ignoring_prefixes_suffixes(self):
        from listing_qc_validator.utils.validators import clean_size_for_comparison
        self.assertEqual(clean_size_for_comparison("Int: S"), "s")
        self.assertEqual(clean_size_for_comparison("UK: 8"), "8")
        self.assertEqual(clean_size_for_comparison("US: 10"), "10")
        self.assertEqual(clean_size_for_comparison("8 yrs-Y"), "8")
        self.assertEqual(clean_size_for_comparison("8 yrs-y"), "8")
        self.assertEqual(clean_size_for_comparison("8 yrs"), "8")
        self.assertEqual(clean_size_for_comparison("8y"), "8")
        self.assertEqual(clean_size_for_comparison("Int: 3XL"), "xxxl")
        self.assertEqual(clean_size_for_comparison("Int: 4XL"), "xxxxl")
        self.assertEqual(clean_size_for_comparison("Int:3XL"), "xxxl")
        self.assertEqual(clean_size_for_comparison("Int:4XL"), "xxxxl")

    def test_parent_sku_validation(self):
        # A parent SKU is not 13 digits (e.g. "404620_PARENT")
        row = pd.Series({
            "article_number": "404620_07",
            "sku": "404620_PARENT", # Parent SKU (not 13 digits)
            "ecommerce_status": "Blocked", # Normally error, but should be skipped
            "launch_date": "2026-06-20", # Valid Launch Date
            "gender": "Kids", # Normally Warning (Men's shoe), but skipped
            "product_name": "Men's Leather Running Shoes Black Edition",
            "color_name": "Red", # Normally Error (reference is Black), but skipped
            "size": "99", # Normally Error (reference size mismatch), but skipped
            "quantity": 15, # Normally Error (must be 0), but skipped
            "price": 1000.0, # Normally Error (reference mismatch), but skipped
            "_original_row_number": 4,
            "_source_file": "test_upload.csv"
        })
        excs = validate_row_internal(
            row, 0,
            channel="Shopee PH",
            content_maps=self.content_maps,
            zecom_maps=self.zecom_maps_shopee
        )
        # We expect 0 exceptions since all non-Article/Launch Date checks are skipped
        # and SKU is not 13 digits is NOT an error.
        self.assertEqual(len(excs), 0, f"Expected 0 exceptions for parent SKU, found: {excs}")

    def test_parent_sku_missing_article_ignored(self):
        row = pd.Series({
            "article_number": "", # Missing! Should be ignored for Parent SKU.
            "sku": "404620_PARENT",
            "launch_date": "2026-06-20",
            "_original_row_number": 5,
            "_source_file": "test_upload.csv"
        })
        excs = validate_row_internal(
            row, 0,
            channel="Shopee PH",
            content_maps=self.content_maps,
            zecom_maps=self.zecom_maps_shopee
        )
        # We expect 0 exceptions since parent SKU validations are ignored.
        self.assertEqual(len(excs), 0, f"Expected 0 exceptions, found: {excs}")

    def test_size_wl_normalization(self):
        from listing_qc_validator.utils.validators import clean_size_for_comparison
        self.assertEqual(clean_size_for_comparison("Int:W28 L30"), "28/30")
        self.assertEqual(clean_size_for_comparison("W28 L32"), "28/32")
        self.assertEqual(clean_size_for_comparison("W30L34"), "30/34")

    def test_gender_product_name_mismatch(self):
        row = self.valid_upload_row.copy()
        row["gender"] = "Male"
        row["product_name"] = "[NEW] PUMA x RICK AND MORTY Unisex Sweatpants (Black)"
        excs = validate_row_internal(
            row, 0,
            channel="Shopee PH",
            content_maps=self.content_maps,
            zecom_maps=self.zecom_maps_shopee
        )
        gender_prod_excs = [e for e in excs if "gender" in e["Message"].lower()]
        self.assertTrue(len(gender_prod_excs) > 0, "Expected a gender-related exception.")

    def test_compare_source_and_live(self):
        # Create a mock source_df (upload sheet)
        source_df = pd.DataFrame([
            {
                "sku": "4069161482557",
                "article_number": "404620_07",
                "size": "42",
                "product_name": "Men's Shoes",
                "color_name": "Black",
                "price": 89.99,
                "quantity": 0,
                "ecommerce_status": "Active"
            }
        ])
        # Create a mock live_df (mismatched color and price)
        live_df = pd.DataFrame([
            {
                "sku": "4069161482557",
                "size": "42",
                "product_name": "Men's Shoes",
                "color_name": "White",       # Mismatched color (reference is Black)
                "price": 99.99,              # Mismatched price (reference is 89.99)
                "quantity": 10,
                "ecommerce_status": "Active"
            }
        ])
        
        comp_df, metrics = compare_source_and_live(
            source_df,
            live_df,
            match_column="sku",
            content_df=self.mock_content_df,
            zecom_df=self.mock_zecom_df,
            channel="Shopee PH"
        )
        
        self.assertFalse(comp_df.empty)
        # Check that we have a Color Name mismatch and it lists the reference color "Black"
        color_records = comp_df[comp_df["Comparison Field"] == "Color Name"]
        self.assertFalse(color_records.empty)
        self.assertEqual(color_records.iloc[0]["Source Value"], "Black")
        self.assertEqual(color_records.iloc[0]["Live Value"], "White")
        self.assertEqual(color_records.iloc[0]["Reference Value"], "Black")
        self.assertEqual(color_records.iloc[0]["Match Status"], "Mismatch")

if __name__ == '__main__':
    unittest.main()
