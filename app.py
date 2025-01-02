import os
import time
import pytesseract
from PIL import Image
import subprocess
import csv
import re
import numpy as np
import cv2

TESSERACT_PATH = r"C:\path\to\your\tesseract.exe"
ADB_PATH = r"C:\path\to\your\adb.exe"
SCRCPY_PATH = r"C:\path\to\your\scrcpy\scrcpy.exe"

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

def run_adb_command(command):
    command.insert(0, ADB_PATH)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running command: {command}")
        print(result.stderr)
        return False
    return True

def capture_screenshot(counter):
    screenshot_path = f"screenshot_{counter}.png"
    if not run_adb_command(["shell", "screencap", "-p", f"/storage/emulated/0/{screenshot_path}"]):
        return None
    if not run_adb_command(["pull", f"/storage/emulated/0/{screenshot_path}", screenshot_path]):
        return None
    return screenshot_path

def preprocess_image(image_path):
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    cv2.imwrite("temp_processed.png", gray)
    return "temp_processed.png"

def extract_text(image_path):
    processed_image_path = preprocess_image(image_path)
    custom_config = r'--oem 3 --psm 6 -l eng+ind'
    text = pytesseract.image_to_string(Image.open(processed_image_path), config=custom_config)
    if os.path.exists(processed_image_path):
        os.remove(processed_image_path)
    return text

class EntryTracker:
    def __init__(self):
        self.last_entries = []
        self.max_entries = 3

    def is_duplicate_or_overlap(self, new_entry):
        if self.last_entries:
            last_entry = self.last_entries[-1]
            
            if (new_entry["Tanggal"] == last_entry["Tanggal"] and 
                self._is_exact_duplicate(new_entry, last_entry)):
                return True
        
        return False

    def _is_exact_duplicate(self, entry1, entry2):
        text1 = f"{entry1['Kegiatan']} {entry1['Target Pencapaian']}".lower()
        text2 = f"{entry2['Kegiatan']} {entry2['Target Pencapaian']}".lower()
        
        text1 = re.sub(r'[,.;]', '', text1)
        text2 = re.sub(r'[,.;]', '', text2)
        
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 or not words2:
            return False
            
        overlap = len(words1.intersection(words2))
        smaller_set_size = min(len(words1), len(words2))
        
        return overlap / smaller_set_size > 0.9

    def add_entry(self, entry):
        self.last_entries.append(entry)
        if len(self.last_entries) > self.max_entries:
            self.last_entries.pop(0)

def parse_text(text):
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    entries = []
    current_entry = {
        "Tanggal": "Unknown",
        "Kegiatan": [],
        "Target Pencapaian": "Unknown"
    }
    
    date_pattern = r'\d{4}-\d{2}-\d{2}'
    in_kegiatan = False
    
    for line in lines:
        date_match = re.search(date_pattern, line)
        if date_match:
            if current_entry["Kegiatan"]:
                current_entry["Kegiatan"] = ' '.join(current_entry["Kegiatan"]) if isinstance(current_entry["Kegiatan"], list) else current_entry["Kegiatan"]
                entries.append(current_entry.copy())
            current_entry = {
                "Tanggal": date_match.group(0),
                "Kegiatan": [],
                "Target Pencapaian": "Unknown"
            }
            in_kegiatan = False
            continue
            
        if any(ui_element in line for ui_element in ['Jurnal', '←', '→', '%', '©', 'Back']):
            continue
            
        if "Kegiatan:" in line:
            in_kegiatan = True
            continue
        elif "Target Pencapaian:" in line:
            in_kegiatan = False
            if isinstance(current_entry["Kegiatan"], list):
                current_entry["Kegiatan"] = ' '.join(current_entry["Kegiatan"])
            continue
        elif "Selesai" in line:
            current_entry["Target Pencapaian"] = "Selesai"
            continue
            
        if in_kegiatan and line and not line.isspace():
            if isinstance(current_entry["Kegiatan"], str):
                current_entry["Kegiatan"] = [current_entry["Kegiatan"]]
            current_entry["Kegiatan"].append(line)
    
    if current_entry["Kegiatan"]:
        current_entry["Kegiatan"] = ' '.join(current_entry["Kegiatan"]) if isinstance(current_entry["Kegiatan"], list) else current_entry["Kegiatan"]
        entries.append(current_entry)
    
    return entries

def main():
    csv_filename = "logs.csv"
    csv_exists = os.path.exists(csv_filename)
    
    with open(csv_filename, mode='a', newline='', encoding='utf-8') as csvfile:
        fieldnames = ["Tanggal", "Kegiatan", "Target Pencapaian"]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not csv_exists:
            writer.writeheader()
    
    counter = 0
    entry_tracker = EntryTracker()
    scroll_distance = 250
    
    try:
        while True:
            screenshot_path = capture_screenshot(counter)
            if screenshot_path is None:
                break
            
            text = extract_text(screenshot_path)
            if not text.strip():
                break
            
            parsed_entries = parse_text(text)
            
            for entry in parsed_entries:
                if entry["Tanggal"] != "Unknown" and entry["Kegiatan"]:
                    if not entry_tracker.is_duplicate_or_overlap(entry):
                        with open(csv_filename, mode='a', newline='', encoding='utf-8') as csvfile:
                            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                            writer.writerow(entry)
                        print(f"Extracted log for {entry['Tanggal']}:")
                        print(f"Activity: {entry['Kegiatan']}")
                        print(f"Target: {entry['Target Pencapaian']}")
                        entry_tracker.add_entry(entry)
            
            os.remove(screenshot_path)
            
            start_y = 1000
            end_y = start_y - scroll_distance
            
            steps = 3
            for step in range(steps):
                current_end = start_y - ((scroll_distance // steps) * (step + 1))
                if not run_adb_command([
                    "shell", "input", "swipe",
                    "540", str(start_y),
                    "540", str(current_end),
                    "150"
                ]):
                    break
                time.sleep(0.3)
            
            time.sleep(0.5)
            counter += 1
            
    except KeyboardInterrupt:
        print("Process interrupted by user.")
    finally:
        print(f"Logs saved to {csv_filename}")

if __name__ == "__main__":
    main()
