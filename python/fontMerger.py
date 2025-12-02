import os
import shutil
from fontTools.ttLib import TTFont
from fontTools.merge import Merger, Options
from gftools.fix import rename_font
from fontTools.subset import Subsetter, Options as SubsetOptions
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

# Set up logging for thread-safe output
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger()

base_input_dir = "used-fonts"
output_dir = "NotoMultilanguageFonts"
temp_subset_dir = "TempSubsetFonts"
os.makedirs(output_dir, exist_ok=True)
os.makedirs(temp_subset_dir, exist_ok=True)

weights = ["Thin", "Light", "Regular", "Medium", "SemiBold", "Bold", "ExtraBold", "Black"]

def is_valid_font(path):
    name = os.path.basename(path).lower()
    return "condensed" not in name and name.endswith(".ttf")

locale_priority = {
    "sc": {"notosanssc": 0, "notosanstc": 1, "notosanshk": 2, "notosansjp": 3, "notosanskr": 4},
    "tc": {"notosanstc": 0, "notosanshk": 1, "notosanssc": 2, "notosansjp": 3, "notosanskr": 4},
    "hk": {"notosanshk": 0, "notosanstc": 1, "notosanssc": 2, "notosansjp": 3, "notosanskr": 4},
    "jp": {"notosansjp": 0, "notosanssc": 1, "notosanstc": 2, "notosanshk": 3, "notosanskr": 4},
    "kr": {"notosanskr": 0, "notosanssc": 1, "notosanstc": 2, "notosanshk": 3, "notosansjp": 4},
}

def process_locale_weight(locale, weight):
    """Process a single (locale, weight) combination. Returns log lines."""
    log_lines = []
    weight_dir = os.path.join(base_input_dir, weight)
    if not os.path.exists(weight_dir):
        msg = f"⚠️  Folder {weight} does not exist. Skipping."
        logger.warning(msg)
        return [msg]

    font_paths_all = [os.path.join(weight_dir, f) for f in os.listdir(weight_dir) if is_valid_font(f)]
    if len(font_paths_all) < 2:
        msg = f"❌ Insufficient fonts. Skipping {weight} for locale {locale}."
        logger.error(msg)
        return [msg]

    priority = locale_priority[locale]
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
            msg = f"⚠️  Failed to read font file {os.path.basename(path)}: {e}"
            logger.warning(msg)
            log_lines.append(msg)

    if rejected_fonts:
        log_lines.append(f"⚠️  The following fonts in {weight} were skipped due to incompatible unitsPerEm:")
        for name, upem in rejected_fonts:
            log_lines.append(f"   - {name} → unitsPerEm = {upem}")

    log_lines.append(f"\n🔢 Glyph counts and character sets for fonts in {weight} (locale: {locale}):")

    cumulative_codepoints = set()
    subset_fonts = []
    task_temp_dir = os.path.join(temp_subset_dir, f"{locale}_{weight}")
    os.makedirs(task_temp_dir, exist_ok=True)

    for path in valid_fonts:
        try:
            font = TTFont(path)
            cmap_table = next((t for t in font["cmap"].tables if t.isUnicode()), None)
            if not cmap_table:
                msg = f"⚠️  Unicode cmap table not found in {os.path.basename(path)}. Skipping."
                logger.warning(msg)
                log_lines.append(msg)
                continue

            cps = set(cmap_table.cmap.keys())
            unique_cps = cps - cumulative_codepoints
            if not unique_cps:
                msg = f"   - {os.path.basename(path)} (glyph count: {len(cps)}) is fully redundant. Skipping."
                log_lines.append(msg)
                continue

            cumulative_codepoints.update(unique_cps)

            # Subset
            subset_font = TTFont(path)
            options = SubsetOptions()
            options.drop_tables += ['GSUB', 'GPOS', 'GDEF']
            subsetter = Subsetter(options=options)
            subsetter.populate(unicodes=unique_cps)
            subsetter.subset(subset_font)

            subset_filename = f"subset_{os.path.basename(path)}"
            subset_path = os.path.join(task_temp_dir, subset_filename)
            subset_font.save(subset_path)
            subset_fonts.append(subset_path)

            msg = f"   - {os.path.basename(path)} (glyph count: {len(cps)}): extracted {len(unique_cps)} unique characters"
            log_lines.append(msg)
            log_lines.append(f"{weight} → {os.path.basename(path)} (glyph count: {len(cps)}) → {len(unique_cps)} characters")
        except Exception as e:
            msg = f"❌ Error processing {path}: {e}"
            logger.error(msg)
            log_lines.append(msg)

    log_lines.append(f"🔢 Total unique characters extracted for {weight} (locale: {locale}): {len(cumulative_codepoints)}")
    log_lines.append(f"🔁 Merging fonts for {weight} ({len(subset_fonts)} subset fonts)...")

    if not subset_fonts:
        msg = f"❌ No new characters to add. Skipping {weight} for locale {locale}."
        logger.error(msg)
        log_lines.append(msg)
        # Clean up task temp dir
        shutil.rmtree(task_temp_dir, ignore_errors=True)
        return log_lines

    try:
        merger = Merger(options=Options(drop_tables=["vmtx", "vhea", "MATH"]))
        merged_font = merger.merge(subset_fonts)

        new_name = f"NotoSans Multilanguage {weight}"
        rename_font(merged_font, new_name)

        output_path = os.path.join(output_dir, f"{locale}-NotoSansMultilanguage-{weight}.ttf")
        merged_font.save(output_path)
        msg = f"✅ Saved: {output_path}"
        logger.info(msg)
        log_lines.append(msg)
        log_lines.append(f"✅ {weight} font successfully saved: {output_path}")
    except Exception as e:
        msg = f"❌ Error: Failed to merge {weight} for locale {locale}. Reason: {e}"
        logger.error(msg)
        log_lines.append(msg)
    finally:
        # Clean up this task's temp dir
        shutil.rmtree(task_temp_dir, ignore_errors=True)

    return log_lines


def main():
    all_tasks = [(locale, weight) for locale in locale_priority for weight in weights]

    all_log_lines = []
    # Adjust max_workers based on your CPU and I/O capacity (e.g., 4–8)
    with ThreadPoolExecutor() as executor:
        future_to_task = {
            executor.submit(process_locale_weight, locale, weight): (locale, weight)
            for locale, weight in all_tasks
        }

        for future in as_completed(future_to_task):
            locale, weight = future_to_task[future]
            try:
                logs = future.result()
                all_log_lines.extend(logs)
            except Exception as e:
                msg = f"❌ Unhandled exception in task ({locale}, {weight}): {e}"
                logger.error(msg)
                all_log_lines.append(msg)

    # Write final log
    # log_path = os.path.join(output_dir, "merge_log.txt")
    # with open(log_path, "w", encoding="utf-8") as log_file:
    #     log_file.write("\n".join(all_log_lines))
    # logger.info(f"\n📄 Final log file generated: {log_path}")

    # Clean up main temp dir (in case any leftover)
    try:
        shutil.rmtree(temp_subset_dir)
        logger.info(f"🧹 Temporary folder deleted: {temp_subset_dir}")
    except Exception as e:
        logger.warning(f"⚠️  Failed to delete temporary folder {temp_subset_dir}: {e}")


if __name__ == "__main__":
    main()