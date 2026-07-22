import sys
import os
import re
import json
import time
import hashlib
import urllib.parse
import urllib.request
import requests

# Ensure UTF-8 stdout encoding across all OS environments
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# ─── CONFIGURATION ───────────────────────────────────────────
DEFAULT_MODELS = [
    'gemini-2.5-flash',
    'gemini-2.0-flash',
    'gemini-3.6-flash',
    'gemini-3.5-flash',
    'gemini-3.5-flash-lite',
    'gemini-3.1-pro-preview',
    'gemini-3.1-flash-lite',
    'gemini-3-flash-preview',
    'gemini-3-pro-preview',
    'gemini-flash-latest',
    'gemini-pro-latest'
]

MAX_HISTORY_HASHES = 2000
HASH_FILE = 'posted_jobs_hash.json'

def get_api_keys():
    keys = []
    env_keys = os.environ.get('GEMINI_API_KEYS', '')
    if env_keys:
        keys.extend([k.strip() for k in env_keys.split(',') if k.strip()])
    for env_var in ['GEMINI_API_KEY', 'GEMINI_API_KEY_2', 'GEMINI_API_KEY_3']:
        val = os.environ.get(env_var, '').strip()
        if val and val not in keys:
            keys.append(val)
    return keys

# ─── ENTRY-LEVEL JOB PROMPT ──────────────────────────────────
def build_job_prompt():
    return (
        "Generate 15 to 20 REAL, active ENTRY-LEVEL job listings across Tamil Nadu, India (Chennai, Coimbatore, Madurai, Trichy, Salem, Tiruppur, Vellore, Erode, Thanjavur).\n"
        "Require 0 YEARS EXPERIENCE / FRESHERS / TRAINEES / BEGINNERS / 10th-12th Pass / Diploma / ITI / Any Graduates.\n\n"
        "STRICT JOB FILTERING & SPECTRUM REQUIREMENTS:\n"
        "- Cover ALL spectrums from low-end entry roles to corporate graduate roles:\n"
        "  * Low-End & Field Entry Roles: Data Entry Operator, BPO Telecaller, Office Assistant, Store Exec, Delivery Associate, Field Technician, Lab Assistant, Warehouse Helper, ITI Trainee.\n"
        "  * High-End & Corporate Entry Roles: Software Fresher / Trainee, Graduate Engineer Trainee (GET), Management Trainee, Junior Analyst, Finance Fresher, Clinical/Pharma Fresher.\n"
        "- Do NOT include senior, manager, or experienced (2+ years) positions.\n"
        "- Provide real/plausible direct application URLs from major portals (Naukri.com, Indeed.in, LinkedIn.com, Glassdoor.in, Fresherworld.com).\n"
        "- Classify each job into ONE category:\n"
        "  IT & Software | Engineering & Technical | BPO & Customer Care | Office & Data Entry | Sales & Marketing | Finance & Banking | Field & Delivery | Healthcare & Others\n\n"
        "Return your answer as a JSON object ONLY. Do not include any text outside the JSON.\n"
        "Format:\n"
        '{"jobs":[{"title":"Software Trainee (Fresher)","company":"Zoho","location":"Chennai",'
        '"link":"https://www.naukri.com/job-listings-software-trainee","job_type":"IT & Software","requirements":"0 years exp, Freshers welcome","salary":"3-5 LPA"}]}'
    )

# ─── GEMINI CALL WITH MODEL RETRIES ───────────────────────────
def call_gemini(model, api_key, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}]
    }
    if "-thinking" in model:
        payload["generationConfig"] = {"thinkingConfig": {"thinkingBudget": 2048}}

    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        candidates = data.get('candidates', [])
        if not candidates or 'content' not in candidates[0] or 'parts' not in candidates[0]['content']:
            raise Exception("Empty candidates or content in Gemini response")
        text = candidates[0]['content']['parts'][0].get('text', '').strip()
        if not text:
            raise Exception("Empty text returned by model")
        return text

def fetch_jobs_via_gemini():
    api_keys = get_api_keys()
    if not api_keys:
        print("[ERROR] No GEMINI_API_KEY environment variables found.")
        return None

    prompt = build_job_prompt()

    for k_idx, key in enumerate(api_keys):
        print(f"[INFO] Trying API Key index {k_idx} ({key[:8]}...)")
        for model in DEFAULT_MODELS:
            print(f"[INFO] Trying model: {model}")
            for attempt in range(1, 4):
                try:
                    res = call_gemini(model, key, prompt)
                    print(f"[SUCCESS] Model {model} succeeded on attempt {attempt}")
                    return res
                except Exception as e:
                    err_str = str(e)
                    print(f"[WARNING] Model {model} (Attempt {attempt}) failed: {err_str[:120]}")
                    if any(code in err_str for code in ['429', '503', '500']):
                        if attempt < 3:
                            sleep_time = attempt * 2
                            print(f"[SLEEP] Sleeping {sleep_time}s for rate limit...")
                            time.sleep(sleep_time)
                            continue
                    break
    print("[ERROR] All Gemini API Keys & Models exhausted.")
    return None

def parse_jobs_json(text):
    if not text:
        return []
    cleaned = text.strip()
    cleaned = re.sub(r'^```json\s*', '', cleaned, flags=re.I)
    cleaned = re.sub(r'^```\s*', '', cleaned, flags=re.I)
    cleaned = re.sub(r'```$', '', cleaned).strip()
    
    match = re.search(r'\{[\s\S]*\}', cleaned)
    if match:
        cleaned = match.group(0)

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data.get('jobs', [])
        elif isinstance(data, list):
            return data
    except Exception as e:
        print(f"[ERROR] Failed to parse JSON: {e}")
    return []

# ─── DEDUPLICATION & HASHING ──────────────────────────────────
def clean_url(url_str):
    if not url_str:
        return ''
    parsed = urllib.parse.urlparse(url_str)
    clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')
    return clean

def compute_hash(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()

def load_posted_hashes():
    if os.path.exists(HASH_FILE):
        try:
            with open(HASH_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('hashes', [])
        except Exception as e:
            print(f"Warning reading hash file: {e}")
    return []

def save_posted_hashes(hashes):
    try:
        with open(HASH_FILE, 'w', encoding='utf-8') as f:
            json.dump({"hashes": hashes}, f, indent=2)
    except Exception as e:
        print(f"Error writing hash file: {e}")

def deduplicate_jobs(jobs):
    existing_hashes = load_posted_hashes()
    new_jobs = []
    new_hashes = []

    for j in jobs:
        title = j.get('title', '').strip()
        company = j.get('company', '').strip()
        link = j.get('link', '').strip()
        if not title or not company:
            continue

        clean_link = clean_url(link)
        link_hash = compute_hash(f"url::{clean_link.lower()}")
        
        norm_title = re.sub(r'[^a-z0-9]', '', title.lower())
        norm_company = re.sub(r'[^a-z0-9]', '', company.lower())
        combo_hash = compute_hash(f"combo::{norm_company}||{norm_title}")

        if link_hash not in existing_hashes and link_hash not in new_hashes and \
           combo_hash not in existing_hashes and combo_hash not in new_hashes:
            new_jobs.append(j)
            if clean_link:
                new_hashes.append(link_hash)
            new_hashes.append(combo_hash)
        else:
            print(f"[SUPPRESSED] Duplicate job: {title} at {company}")

    if new_jobs:
        updated = existing_hashes + new_hashes
        if len(updated) > MAX_HISTORY_HASHES:
            updated = updated[-MAX_HISTORY_HASHES:]
        save_posted_hashes(updated)

    return new_jobs

# ─── TELEGRAM BROADCASTING ───────────────────────────────────
def esc(text):
    if not text:
        return ''
    return str(text).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def format_message(jobs):
    order = [
        'IT & Software',
        'Engineering & Technical',
        'BPO & Customer Care',
        'Office & Data Entry',
        'Sales & Marketing',
        'Finance & Banking',
        'Field & Delivery',
        'Healthcare & Others'
    ]
    cat_emojis = {
        'IT & Software': '💻',
        'Engineering & Technical': '⚙️',
        'BPO & Customer Care': '📞',
        'Office & Data Entry': '🏢',
        'Sales & Marketing': '📣',
        'Finance & Banking': '🏦',
        'Field & Delivery': '🚚',
        'Healthcare & Others': '🏥'
    }

    categories = {}
    for j in jobs:
        cat = j.get('job_type') if j.get('job_type') in order else 'Healthcare & Others'
        categories.setdefault(cat, []).append(j)

    curr_time = time.strftime('%d %b %Y, %I:%M %p')
    msg = f"🎓 <b>Tamil Nadu Entry-Level & Fresher Jobs</b>\n⏰ <i>{curr_time} IST</i>\n📌 <i>No Experience Required (0 Years / Freshers / Trainees)</i>\n\n"

    for cat in order:
        if cat not in categories:
            continue
        emoji = cat_emojis.get(cat, '📁')
        msg += f"{emoji} <b>{cat}</b>\n"
        for j in categories[cat]:
            msg += f"• <b>{esc(j.get('title'))}</b>\n"
            msg += f"  🏢 {esc(j.get('company'))} | 📍 {esc(j.get('location'))}"
            if j.get('salary'):
                msg += f" | 💰 {esc(j.get('salary'))}"
            msg += "\n"
            if j.get('requirements'):
                msg += f"  🎓 {esc(j.get('requirements'))}\n"
            msg += f"  🔗 <a href=\"{esc(j.get('link'))}\">Apply Now</a>\n\n"

    msg += "👉 Join <b>@JOB_PORTAL_TAMILNADU</b> for Entry-Level & Fresher jobs every 10 minutes!"
    return msg

def send_to_telegram(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = []
    if len(text) <= 4096:
        chunks.append(text)
    else:
        current = ""
        for line in text.split('\n'):
            if len(current + line + '\n') > 4000:
                if current.strip():
                    chunks.append(current)
                current = ""
            current += line + '\n'
        if current.strip():
            chunks.append(current)

    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        res = requests.post(url, json=payload, timeout=30)
        if res.status_code != 200:
            print(f"[ERROR] Telegram Error {res.status_code}: {res.text[:200]}")
        else:
            print("[SUCCESS] Broadcasted entry-level job chunk to Telegram successfully.")

# ─── MAIN ENTRYPOINT ──────────────────────────────────────────
def main():
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if not bot_token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in environment.")
        return

    print("[INFO] Starting 10-Minute Entry-Level Job Fetch Cycle...")
    raw_response = fetch_jobs_via_gemini()
    if not raw_response:
        print("[ERROR] Gemini returned no data.")
        return

    jobs = parse_jobs_json(raw_response)
    print(f"[INFO] Fetched raw entry-level jobs: {len(jobs)}")
    if not jobs:
        print("[INFO] No job listings parsed.")
        return

    new_jobs = deduplicate_jobs(jobs)
    print(f"[INFO] New unique entry-level jobs after deduplication: {len(new_jobs)}")
    if not new_jobs:
        print("[INFO] All jobs were previously posted. Skipping broadcast.")
        return

    message = format_message(new_jobs)
    send_to_telegram(bot_token, chat_id, message)
    print("[SUCCESS] Entry-level job cycle completed successfully.")

if __name__ == '__main__':
    main()
