"""
Execution Script: Send WhatsApp DMs (Selenium Version)

This script reads a CSV file containing business names and phone numbers,
cleans the phone numbers to standard format (+251), and sends a personalized
WhatsApp message using Selenium. 

This approach prevents new tabs from opening and closing constantly. It uses
a dedicated Chrome profile so you only have to scan the QR code once.
"""

import pandas as pd
import time
import random
import os
import sys
from urllib.parse import quote
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys

def clean_phone_number(raw_phone):
    if pd.isna(raw_phone) or not str(raw_phone).strip():
        return None
    clean_num = str(raw_phone).replace(" ", "").replace("-", "")
    if clean_num.startswith("09"):
        clean_num = "+251" + clean_num[1:]
    if not clean_num.startswith("+251"):
        return None
    return clean_num

def clean_business_name(raw_name):
    if pd.isna(raw_name):
        return "Business Owner"
    return str(raw_name).split('|')[0].strip()

def send_whatsapp_campaign(csv_path, message_template, sent_log_path):
    if not os.path.exists(csv_path):
        print(f"Error: Could not find file at {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)

    greetings = ["Hello", "Hi", "Greetings"]

    sent_numbers = set()
    if os.path.exists(sent_log_path):
        with open(sent_log_path, 'r') as f:
            sent_numbers = set([line.strip() for line in f.readlines() if line.strip()])
    print(f"Loaded {len(sent_numbers)} previously sent numbers to skip.")

    # Setup Selenium
    print("Starting Chrome. Please do not close the browser window...")
    options = webdriver.ChromeOptions()
    
    # Store the session data so we don't have to scan QR code every time
    profile_dir = os.path.join(os.getcwd(), "whatsapp_profile_v3")
    options.add_argument(f"user-data-dir={profile_dir}")
    
    # Stability flags to prevent Chrome crashes
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    
    try:
        driver = webdriver.Chrome(options=options)
    except Exception as e:
        print(f"Failed to launch Chrome. Please ensure Google Chrome is installed. Error: {e}")
        sys.exit(1)

    success_count = 0
    skip_count = 0

    try:
        driver.get("https://web.whatsapp.com")
        print("Waiting 30 seconds for you to scan the QR code (if not already logged in)...")
        time.sleep(30)

        for index, row in df.iterrows():
            raw_phone = row['phone']
            raw_name = row['name']

            phone = clean_phone_number(raw_phone)
            name = clean_business_name(raw_name)

            if not phone:
                skip_count += 1
                continue

            if phone in sent_numbers:
                print(f"[Skip] Already sent to {name} ({phone}) previously.")
                skip_count += 1
                continue

            greeting = random.choice(greetings)
            message = message_template.replace("{{restaurant}}", name)
            full_message = f"{greeting} {message}"
            
            print(f"\n[Sending] to {name} ({phone})...")
            
            # Navigate to the chat in the same window
            encoded_message = quote(full_message)
            url = f"https://web.whatsapp.com/send?phone={phone}&text={encoded_message}"
            driver.get(url)

            try:
                # Wait up to 35 seconds for the send button to appear and become clickable
                # The send button usually has a data-icon="send"
                print("Waiting for chat to load...")
                time.sleep(5) # buffer for the initial loading modal
                try:
                    send_button = WebDriverWait(driver, 30).until(
                        EC.element_to_be_clickable((By.XPATH, '//span[@data-icon="send"]'))
                    )
                    time.sleep(random.uniform(1.0, 3.0))
                    send_button.click()
                except:
                    # Fallback: just send ENTER to the active element
                    print("Send button not found, attempting ENTER key fallback...")
                    driver.switch_to.active_element.send_keys(Keys.ENTER)
                
                success_count += 1
                print("Successfully sent!")
                
                # Log the successful send to prevent duplicates in future runs
                with open(sent_log_path, 'a') as f:
                    f.write(phone + "\n")
                sent_numbers.add(phone)
                
                # Anti-ban delay: Sleep between 45 and 90 seconds (per directive)
                sleep_time = random.randint(45, 90)
                print(f"Sleeping for {sleep_time} seconds to mimic human behavior and avoid bans...")
                time.sleep(sleep_time)

            except Exception as e:
                print(f"[Error] Failed to send to {phone}. This number might not be on WhatsApp or page loaded too slowly.")

    except KeyboardInterrupt:
        print("\n[Interrupted] You stopped the script manually.")
    except Exception as e:
        print(f"\n[Fatal Error] {e}")
    finally:
        print("\n--------------------------------------------------------------------------------")
        print(f"Campaign Finished. Sent: {success_count} | Skipped: {skip_count}")
        driver.quit()
        print("Browser safely closed. You can run the script again anytime.")

if __name__ == "__main__":
    target_csv = r"c:\Users\NH RICH\Documents\Adiss Abbeba clients\output\restaurants_addis_abeba.csv"
    sent_log = r"c:\Users\NH RICH\Documents\Adiss Abbeba clients\output\sent_numbers.txt"
    
    # Updated message template per user request
    base_template = "We help restaurants with digital menu solutions, and I’m reaching out to see if you currently have a digital menu for your customers."
    
    # Run the campaign
    send_whatsapp_campaign(target_csv, base_template, sent_log)
