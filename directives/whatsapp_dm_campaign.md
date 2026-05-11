# Directive: WhatsApp DM Campaign Automation

## Objective
Automate the process of sending personalized, bulk WhatsApp Direct Messages to scraped entities (e.g., restaurants, supermarkets) using browser automation (`selenium`).

## Strategy to Bypass Anti-Spam
1. **Message Hashing Avoidance**: Inject a variable (the business name) and randomly rotate the greeting (spintax) so no two messages are exactly the same.
2. **Human Mimicry (Timing)**: REMOVED per user instruction. Sending instantly. High risk of ban accepted.
3. **Data Cleaning**: Automatically reformat local phone numbers (`09...`) to international standards (`+2519...`).

## Inputs
- **Source**: A CSV file containing at minimum a `name` column and a `phone` column. (e.g., `output/restaurants_addis_abeba.csv`)

## Outputs
- **Direct Output**: Messages sent directly via WhatsApp Web.
- **State/Log**: A text file (`output/sent_numbers.txt`) that tracks every successfully sent phone number to ensure we never send duplicate messages across multiple runs.
- **Log**: Console output detailing which messages succeeded and which were skipped.

## Execution Requirements
- **Script**: `execution/send_whatsapp_dms.py`
- **Dependencies**: `selenium`, `pandas`
- **Environment**: A Windows machine with Google Chrome installed. The script uses a dedicated Chrome profile so you only scan the QR code once.

## Operational Constraints & Risks
- **WARNING**: Do NOT use a primary personal or business phone number. The risk of being flagged by Meta for spam is high if users manually report the messages. Use a secondary SIM.
- **Browser State**: The script opens a single dedicated Chrome window. It navigates between chats internally, so it won't spam your screen with new tabs. Please leave the window open and unlocked during execution.
