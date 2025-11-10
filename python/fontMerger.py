import os
import shutil
from fontTools.ttLib import TTFont
from fontTools.merge import Merger, Options
from gftools.fix import rename_font
from fontTools.subset import Subsetter, Options as SubsetOptions

base_input_dir = "used-fonts"
output_dir = "NotoMultilanguageFonts"
temp_subset_dir = "TempSubsetFonts"
os.makedirs(output_dir, exist_ok=True)
os.makedirs(temp_subset_dir, exist_ok=True)

weights = ["Thin", "Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black"]

def is_valid_font(path):
    name = os.path.basename(path).lower()
    return "condensed" not in name and name.endswith(".ttf")

# Initialize log content
log_lines = []

for weight in weights:
    weight_dir = os.path.join(base_input_dir, weight)
    if not os.path.exists(weight_dir):
        print(f"⚠️  Folder {weight} does not exist. Skipping.")
        continue

    font_paths_all = [os.path.join(weight_dir, f) for f in os.listdir(weight_dir) if is_valid_font(f)]
    if len(font_paths_all) < 2:
        print(f"❌ Insufficient fonts. Skipping {weight}.")
        continue

    # Priority order: NotoSansSC > NotoSansTC > NotoSansHK > NotoSansJP > NotoSansKR
    priority = {"notosanssc": 0, "notosanstc": 1, "notosanshk": 2, "notosansjp": 3, "notosanskr": 4}
    def sort_key(path):
        name = os.path.basename(path).lower()
        for key, value in priority.items():
            if key in name:
                return value
        return 99
    font_paths_all.sort(key=sort_key)

    valid_fonts = []
    rejected_fonts = []
    for path in font_paths_all:
        try:
            font = TTFont(path)
            upem = font["head"].unitsPerEm
            if upem == 1000:
                valid_fonts.append(path)
            else:
                rejected_fonts.append((os.path.basename(path), upem))
        except Exception as e:
            print(f"⚠️  Failed to read font file {os.path.basename(path)}: {e}")

    if rejected_fonts:
        print(f"⚠️  The following fonts in {weight} were skipped due to incompatible unitsPerEm:")
        for name, upem in rejected_fonts:
            print(f"   - {name} → unitsPerEm = {upem}")

    print(f"\n🔢 Glyph counts and character sets for fonts in {weight}:")

    cumulative_codepoints = set()
    subset_fonts = []

    for path in valid_fonts:
        font = TTFont(path)
        cmap_table = next((t for t in font["cmap"].tables if t.isUnicode()), None)
        if not cmap_table:
            print(f"⚠️  Unicode cmap table not found in {os.path.basename(path)}. Skipping.")
            continue

        cps = set(cmap_table.cmap.keys())
        unique_cps = cps - cumulative_codepoints
        if not unique_cps:
            print(f"   - {os.path.basename(path)} (glyph count: {len(cps)}) is fully redundant. Skipping.")
            continue

        cumulative_codepoints.update(unique_cps)

        # Perform subsetting
        subset_font = TTFont(path)
        options = SubsetOptions()
        options.drop_tables += ['GSUB', 'GPOS', 'GDEF']
        subsetter = Subsetter(options=options)
        subsetter.populate(unicodes=unique_cps)
        subsetter.subset(subset_font)

        subset_path = os.path.join(temp_subset_dir, f"subset_{os.path.basename(path)}")
        subset_font.save(subset_path)
        subset_fonts.append(subset_path)

        print(f"   - {os.path.basename(path)} (glyph count: {len(cps)}): extracted {len(unique_cps)} unique characters")
        log_lines.append(f"{weight} → {os.path.basename(path)}(glyph count: {len(cps)}) → {len(unique_cps)} characters")

    print(f"🔢 Total unique characters extracted for {weight}: {len(cumulative_codepoints)}")
    print(f"🔁 Merging fonts for {weight} ({len(subset_fonts)} subset fonts)...")

    if not subset_fonts:
        print(f"❌ No new characters to add. Skipping {weight}.")
        continue

    try:
        merger = Merger(options=Options(drop_tables=["vmtx", "vhea", "MATH"]))
        merged_font = merger.merge(subset_fonts)

        new_name = f"NotoSans Multilanguage {weight}"
        rename_font(merged_font, new_name)

        output_path = os.path.join(output_dir, f"NotoSansMultilanguage-{weight}.ttf")
        merged_font.save(output_path)
        print(f"✅ Saved: {output_path}")
        log_lines.append(f"✅ {weight} font successfully saved: {output_path}")
    except Exception as e:
        print(f"❌ Error: Failed to merge {weight}. Reason: {e}")
        log_lines.append(f"❌ Merge failed for {weight}: {e}")

# 📄 Write log file
log_path = os.path.join(output_dir, "merge_log.txt")
with open(log_path, "w", encoding="utf-8") as log_file:
    log_file.write("\n".join(log_lines))
print(f"\n📄 Log file generated: {log_path}")

# 🧹 Clean up temporary subset directory
try:
    shutil.rmtree(temp_subset_dir)
    print(f"🧹 Temporary folder deleted: {temp_subset_dir}")
except Exception as e:
    print(f"⚠️  Failed to delete temporary folder {temp_subset_dir}: {e}")