/**
 * TELEGRAM ENTRY-LEVEL JOB PORTAL BOT - Tamil Nadu Jobs
 * Channel: @JOB_PORTAL_TAMILNADU
 * GitHub Repository: https://github.com/heisenricher/telegram_job_portal
 */

var CONFIG = {
  TELEGRAM_CHAT_ID:  '@JOB_PORTAL_TAMILNADU',
  MAX_HISTORY_HASHES: 2000,
  MODELS: [
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
};

function getConfig(key) {
  var val = PropertiesService.getScriptProperties().getProperty(key);
  return (val && val.trim() !== '') ? val.trim() : CONFIG[key];
}

function setupTrigger() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === 'runEvery10Mins') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('runEvery10Mins').timeBased().everyMinutes(10).create();
}

function runEvery10Mins() {
  var token = getConfig('TELEGRAM_BOT_TOKEN');
  var chatId = getConfig('TELEGRAM_CHAT_ID');
  if (!token) return;

  var jobData = callGeminiWithFallback(buildJobPrompt());
  if (!jobData) return;

  var jobs = parseJobsJson(jobData);
  var newJobs = deduplicateJobs(jobs);
  if (newJobs.length > 0) {
    sendToTelegram(token, chatId, formatJobMessage(newJobs));
  }
}

function parseJobsJson(rawText) {
  if (!rawText) return [];
  try {
    var text = rawText.trim().replace(/^```json\s*/i, '').replace(/```$/, '').trim();
    var match = text.match(/\{[\s\S]*\}/);
    if (match) text = match[0];
    var parsed = JSON.parse(text);
    return parsed.jobs || [];
  } catch (e) {
    return [];
  }
}

function buildJobPrompt() {
  return 'Search Google for brand new ENTRY-LEVEL job openings in Tamil Nadu, India (0 years exp / Freshers / Trainees / Beginners / 10th-12th Pass / Graduates).\n' +
         'Cover ALL spectrums from low-end (Data Entry, BPO, Office Assistant, Delivery, Retail Exec, Field Tech) to high-end (Software Fresher, GET, Management Trainee).\n' +
         'Return answer as JSON object: {"jobs":[{"title":"...","company":"...","location":"...","link":"...","job_type":"IT & Software","requirements":"0 years exp"}]}';
}

function getApiKeys() {
  var keys = [];
  var propsKeys = getConfig('GEMINI_API_KEYS');
  if (propsKeys) {
    propsKeys.split(',').forEach(function(k) { if (k.trim()) keys.push(k.trim()); });
  }
  var k1 = getConfig('GEMINI_API_KEY');
  if (k1 && keys.indexOf(k1) === -1) keys.push(k1);
  return keys;
}

function callGeminiWithFallback(prompt) {
  var keys = getApiKeys();
  var models = CONFIG.MODELS;
  for (var k = 0; k < keys.length; k++) {
    for (var m = 0; m < models.length; m++) {
      for (var attempt = 1; attempt <= 3; attempt++) {
        try {
          return callGemini(models[m], keys[k], prompt);
        } catch (e) {
          if (attempt < 3) Utilities.sleep(attempt * 2000);
        }
      }
    }
  }
  return null;
}

function callGemini(model, apiKey, prompt) {
  var url = 'https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent?key=' + apiKey;
  var payload = { contents: [{ role: 'user', parts: [{ text: prompt }] }], tools: [{ googleSearch: {} }] };
  var options = { method: 'post', contentType: 'application/json', payload: JSON.stringify(payload), muteHttpExceptions: true };
  var res = UrlFetchApp.fetch(url, options);
  var json = JSON.parse(res.getContentText());
  return json.candidates[0].content.parts[0].text;
}

function deduplicateJobs(jobs) {
  var props = PropertiesService.getScriptProperties();
  var stored = props.getProperty('POSTED_JOB_HASHES');
  var hashes = stored ? JSON.parse(stored) : [];
  var newJobs = [], newHashes = [];

  jobs.forEach(function(job) {
    if (!job.title || !job.company) return;
    var normTitle = job.title.toLowerCase().replace(/[^a-z0-9]/g, '');
    var normCompany = job.company.toLowerCase().replace(/[^a-z0-9]/g, '');
    var hash = computeHash(normCompany + '||' + normTitle);
    if (hashes.indexOf(hash) === -1 && newHashes.indexOf(hash) === -1) {
      newJobs.push(job);
      newHashes.push(hash);
    }
  });

  if (newJobs.length > 0) {
    var all = hashes.concat(newHashes);
    if (all.length > 2000) all = all.slice(all.length - 2000);
    props.setProperty('POSTED_JOB_HASHES', JSON.stringify(all));
  }
  return newJobs;
}

function computeHash(str) {
  var raw = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_1, str, Utilities.Charset.UTF_8);
  return raw.map(function(b) { var v = b < 0 ? b + 256 : b; return (v < 16 ? '0' : '') + v.toString(16); }).join('');
}

function formatJobMessage(jobs) {
  var msg = '🎓 <b>Tamil Nadu Entry-Level & Fresher Jobs</b>\n📌 <i>No Experience Required</i>\n\n';
  jobs.forEach(function(j) {
    msg += '• <b>' + esc(j.title) + '</b> (' + esc(j.company) + ')\n';
    msg += '  🔗 <a href="' + esc(j.link) + '">Apply Now</a>\n\n';
  });
  return msg;
}

function esc(t) {
  return t ? t.toString().replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : '';
}

function sendToTelegram(token, chatId, text) {
  var url = 'https://api.telegram.org/bot' + token + '/sendMessage';
  UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: JSON.stringify({ chat_id: chatId, text: text, parse_mode: 'HTML', disable_web_page_preview: true })
  });
}
