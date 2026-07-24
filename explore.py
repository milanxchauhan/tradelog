import glob
import pandas as pd

matches = glob.glob("*.xlsx")
if not matches:
    raise SystemExit("No .xlsx found in this folder. Upload it here first.")
XL = matches[0]
print(f"Reading: {XL}\n")

# Mapping sheet: headers are on row 2, so skip row 1
mapping = pd.read_excel(XL, sheet_name="Mapping", header=1)
mapping = mapping.dropna(subset=["Contract "])
print("=== MAPPING ===")
print(f"rows: {len(mapping)}")
print(mapping[["Category", "Sub-Category", "Contract ", "TT Code",
               "Product", "Tick Size", "Tick Value", "RT ", "Exchange"]].head(10))
print("\nunique products:", sorted(mapping["Product"].dropna().unique()))

print("\n=== ASE MAPPING ===")
ase = pd.read_excel(XL, sheet_name="ASE Mapping")
print(f"rows: {len(ase)}")
print(ase.head(10))

print("\n=== FILL BOOK ===")
fills = pd.read_excel(XL, sheet_name="Fill Book", header=1)
print(f"rows: {len(fills)}")
print(fills[["Date", "Time", "Exchange", "Contract", "Buy/Sell", "Lots", "Price"]].head(10))
print("\ndtypes:")
print(fills[["Date", "Time", "Lots", "Price"]].dtypes)
print("\nBuy/Sell values:", fills["Buy/Sell"].dropna().unique())
print("Exchange values:", fills["Exchange"].dropna().unique())