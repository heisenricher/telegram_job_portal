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
    'gemini-3.6-flash',
    'gemini-3.5-flash',
    'gemini-3.5-flash-lite',
    'gemini-3.1-pro-preview',
    'gemini-3.1-flash-lite',
    'gemini-3-flash-preview',
    'gemini-3-pro-preview',
    'gemini-2.0-flash',
    'gemini-2.0-flash-lite',
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

def build_job_prompt():
    return (
        "Search Google for brand new job openings in Tamil Nadu, India posted TODAY or in the LAST 24 HOURS. "
        "Search across these portals: Naukri.com, Indeed.in, LinkedIn.com, Shine.com, "
        "Timesjobs.com, Glassdoor.in, Fresherworld.com. "
        "Focus on cities: Chennai, Coimbatore, Madurai, Trichy, Salem, Tiruppur, Vellore, Erode, Thanjavur.\n\n"
        "IMPORTANT INSTRUCTIONS:\n"
        "- Find 10 to 20 REAL, freshly posted job listings with actual company names and direct application URLs.\n"
        "- Do NOT make up or hallucinate jobs. Only include genuine jobs found in search results.\n"
        "- Include only jobs where you can extract a direct link to apply or view job details.\n"
        "- Pick individual job listing URLs rather than search results landing pages.\n"
        "- Classify each job into ONE category: IT & Software | Engineering & Manufacturing | "
        "Healthcare & Pharma | Sales & Marketing | Finance & Banking | Govt & PSU | Others\n\n"
        "Return your answer as a JSON object ONLY. Do not include any explanation or text outside the JSON.\n"
        "Format:\n"
        '{"jobs":[{"title":"Software Engineer","company":"TCS","location":"Chennai",'
        '"link":"https://...","job_type":"IT & Software","requirements":"3+ years Java experience","salary":"8-12 LPA"}]}'
    )

# ─── GEMINI CALL WITH MULTI-KEY & BACKOFF ─────────────────────
def call_gemini(model, api_key, prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"googleSearch": {}}]
    }
    if "-thinking" in model:
        payload["generationConfig"] = {"thinkingConfig": {"thinkingBudget": 2048}}

    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            parts = data['candidates'][0]['content']['parts']
            return parts[0]['text']
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        if "googleSearch" in body or "UNKNOWN" in body:
            payload["tools"] = [{"google_search": {}}]
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data['candidates'][0]['content']['parts'][0]['text']
        elif "tools" in body or "grounding" in body:
            del payload["tools"]
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data['candidates'][0]['content']['parts'][0]['text']
        else:
            raise Exception(f"HTTP {e.code}: {body[:200]}")

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
    order = ['IT & Software', 'Engineering & Manufacturing', 'Healthcare & Pharma',
             'Sales & Marketing', 'Finance & Banking', 'Govt & PSU', 'Others']
    cat_emojis = {
        'IT & Software': '💻',
        'Engineering & Manufacturing': '⚙️',
        'Healthcare & Pharma': '🏥',
        'Sales & Marketing': '📣',
        'Finance & Banking': '🏦',
        'Govt & PSU': '🏛️',
        'Others': '📁'
    }

    categories = {}
    for j in jobs:
        cat = j.get('job_type') if j.get('job_type') in order else 'Others'
        categories.setdefault(cat, []).append(j)

    curr_time = time.strftime('%d %b %Y, %I:%M %p')
    msg = f"💼 <b>Tamil Nadu Job Openings</b>\n⏰ <i>{curr_time} IST</i>\n\n"

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
                msg += f"  📝 {esc(j.get('requirements'))}\n"
            msg += f"  🔗 <a href=\"{esc(j.get('link'))}\">Apply Now</a>\n\n"

    msg += "👉 Join <b>@JOB_PORTAL_TAMILNADU</b> for fresh jobs every 10 minutes!"
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
            print("[SUCCESS] Broadcasted job chunk to Telegram successfully.")

# ─── MAIN ENTRYPOINT ──────────────────────────────────────────
def main():
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if not bot_token or not chat_id:
        print("[ERROR] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing in environment.")
        return

    print("[INFO] Starting 10-Minute Job Fetch Cycle via GitHub Actions...")
    raw_response = fetch_jobs_via_gemini()
    if not raw_response:
        print("[ERROR] Gemini returned no data.")
        return

    jobs = parse_jobs_json(raw_response)
    print(f"[INFO] Fetched raw jobs: {len(jobs)}")
    if not jobs:
        print("[INFO] No job listings parsed.")
        return

    new_jobs = deduplicate_jobs(jobs)
    print(f"[INFO] New unique jobs after deduplication: {len(new_jobs)}")
    if not new_jobs:
        print("[INFO] All jobs were previously posted. Skipping broadcast.")
        return

    message = format_message(new_jobs)
    send_to_telegram(bot_token, chat_id, message)
    print("[SUCCESS] Job cycle completed successfully.")

if __name__ == '__main__':
    main()
