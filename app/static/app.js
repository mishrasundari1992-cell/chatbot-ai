const messages = document.querySelector('#messages');
const chatForm = document.querySelector('#chat-form');
const input = document.querySelector('#message');
const sendButton = document.querySelector('#send-message');
const microphoneButton = document.querySelector('#microphone');
const voiceStatus = document.querySelector('#voice-status');
const voiceNotice = document.querySelector('#voice-notice');
const languageSelect = document.querySelector('#voice-language');
const voiceSelect = document.querySelector('#voice-choice');
const rateSelect = document.querySelector('#voice-rate');
const stopSpeakingButton = document.querySelector('#stop-speaking');
const leadForm = document.querySelector('#lead-form');
const leadStatus = document.querySelector('#lead-status');
const careerForm = document.querySelector('#career-form');
const careerStatus = document.querySelector('#career-status');
let conversationId = sessionStorage.getItem('conversationId');
let recognition = null;
let isListening = false;

function setVoiceStatus(state, detail = '') {
  voiceStatus.textContent = `Voice: ${state}${detail ? ` — ${detail}` : ''}`;
  microphoneButton.classList.toggle('listening', state === 'listening');
  microphoneButton.setAttribute('aria-pressed', String(state === 'listening'));
  microphoneButton.setAttribute('aria-label', state === 'listening' ? 'Stop voice input' : 'Start voice input');
}

function showVoiceNotice(message) {
  voiceNotice.textContent = message;
  voiceNotice.classList.remove('hidden');
}

function speak(text) {
  if (!('speechSynthesis' in window)) {
    showVoiceNotice('Speech playback is not supported by this browser. Text chat is still available.');
    return;
  }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = languageSelect.value;
  utterance.rate = Number(rateSelect.value);
  const selectedVoice = window.speechSynthesis.getVoices().find(voice => voice.name === voiceSelect.value);
  if (selectedVoice) utterance.voice = selectedVoice;
  utterance.onstart = () => { stopSpeakingButton.disabled = false; setVoiceStatus('speaking'); };
  utterance.onend = () => { stopSpeakingButton.disabled = true; setVoiceStatus('stopped'); };
  utterance.onerror = () => { stopSpeakingButton.disabled = true; setVoiceStatus('stopped', 'speech playback failed'); };
  window.speechSynthesis.speak(utterance);
}

function renderBasicMarkdown(node, text) {
  node.replaceChildren();
  const lines = String(text).split('\n');
  lines.forEach((line, lineIndex) => {
    const parts = line.split(/(\*\*[^*\n]+\*\*)/g);
    parts.forEach(part => {
      if (part.startsWith('**') && part.endsWith('**') && part.length > 4) {
        const strong = document.createElement('strong');
        strong.textContent = part.slice(2, -2);
        node.appendChild(strong);
      } else {
        node.appendChild(document.createTextNode(part));
      }
    });
    if (lineIndex < lines.length - 1) node.appendChild(document.createElement('br'));
  });
}

function addMessage(text, type, sources = []) {
  const node = document.createElement('div');
  node.className = `message ${type}`;
  node.textContent = text;
  if (type === 'bot') {
    const row = document.createElement('div');
    row.className = 'message-row bot-row';
    row.appendChild(node);
    const speaker = document.createElement('button');
    speaker.type = 'button';
    speaker.className = 'speak-button';
    speaker.textContent = '🔊';
    speaker.title = 'Read this response aloud';
    speaker.setAttribute('aria-label', 'Read assistant response aloud');
    speaker.addEventListener('click', () => speak(node.textContent));
    row.appendChild(speaker);
    messages.appendChild(row);
  } else messages.appendChild(node);
  if (sources.length) {
    const src = document.createElement('div');
    src.className = 'sources';
    src.textContent = `Sources: ${sources.join(', ')}`;
    messages.appendChild(src);
  }
  messages.scrollTop = messages.scrollHeight;
  return node;
}

function populateVoices() {
  if (!('speechSynthesis' in window)) return;
  const previous = voiceSelect.value;
  const language = languageSelect.value.toLowerCase().split('-')[0];
  voiceSelect.replaceChildren(new Option('Browser default', ''));
  window.speechSynthesis.getVoices().filter(voice => voice.lang.toLowerCase().startsWith(language)).forEach(voice => voiceSelect.add(new Option(`${voice.name} (${voice.lang})`, voice.name)));
  if ([...voiceSelect.options].some(option => option.value === previous)) voiceSelect.value = previous;
}

function startRecognition() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) {
    showVoiceNotice('Voice input is not supported by this browser. You can continue using text chat.');
    setVoiceStatus('stopped', 'speech recognition unavailable');
    return;
  }
  // Recognition is constructed and started only from the microphone click handler.
  recognition = new Recognition();
  recognition.lang = languageSelect.value;
  recognition.interimResults = false;
  recognition.continuous = false;
  recognition.onstart = () => { isListening = true; setVoiceStatus('listening', `speak in ${languageSelect.options[languageSelect.selectedIndex].text}`); };
  recognition.onspeechend = () => setVoiceStatus('processing');
  recognition.onresult = event => {
    setVoiceStatus('processing');
    const transcript = Array.from(event.results).map(result => result[0].transcript).join(' ').trim();
    if (transcript) { input.value = transcript; input.focus(); }
  };
  recognition.onerror = event => {
    const errors = {'not-allowed': 'Microphone permission was denied.', 'audio-capture': 'No working microphone was found.', 'no-speech': 'No speech was detected.', network: 'Speech recognition could not connect.'};
    showVoiceNotice(`${errors[event.error] || 'Voice input failed.'} You can continue using text chat.`);
  };
  recognition.onend = () => { isListening = false; setVoiceStatus('stopped'); };
  try {
    recognition.start();
  } catch (error) {
    isListening = false;
    setVoiceStatus('stopped', 'microphone could not start');
    showVoiceNotice('Voice input could not start. You can continue using text chat.');
  }
}

microphoneButton.addEventListener('click', () => {
  if (isListening && recognition) recognition.stop();
  else startRecognition();
});
stopSpeakingButton.addEventListener('click', () => { window.speechSynthesis.cancel(); stopSpeakingButton.disabled = true; setVoiceStatus('stopped'); });
languageSelect.addEventListener('change', populateVoices);

if ('speechSynthesis' in window) {
  populateVoices();
  window.speechSynthesis.addEventListener('voiceschanged', populateVoices);
} else {
  voiceSelect.disabled = true;
  rateSelect.disabled = true;
  showVoiceNotice('Speech playback is not supported by this browser. You can continue using text chat.');
}
if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) {
  microphoneButton.disabled = true;
  showVoiceNotice('Voice input is not supported by this browser. You can continue using text chat.');
}

const pageMode = new URLSearchParams(window.location.search).get('mode');
if (pageMode === 'careers') {
  addMessage('Welcome to ITSIPL Careers. Use “Apply for a job” to submit your profile. Recruitment enquiries are not handled through Sales, Import or Management phone numbers.', 'bot');
  careerForm.classList.remove('hidden');
} else {
  addMessage('Hello! Ask me anything about our company, services, policies, technical support, or careers.', 'bot');
}
chatForm.addEventListener('submit', async event => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message) return;
  await sendChatMessage(message);
});

async function sendChatMessage(message) {
  addMessage(message, 'user');
  input.value = '';
  const pending = addMessage('Thinking…', 'bot');
  sendButton.disabled = true;
  try {
    const response = await fetch('/api/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message, conversation_id: conversationId})});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to answer right now.');
    conversationId = data.conversation_id;
    sessionStorage.setItem('conversationId', conversationId);
    renderBasicMarkdown(pending, data.answer);
    if (data.sources.length) { const src = document.createElement('div'); src.className = 'sources'; src.textContent = `Sources: ${data.sources.join(', ')}`; messages.appendChild(src); }
  } catch (error) { pending.textContent = error.message; }
  finally { sendButton.disabled = false; input.focus(); messages.scrollTop = messages.scrollHeight; }
}

document.querySelector('#lead-toggle').addEventListener('click', () => leadForm.classList.toggle('hidden'));
document.querySelector('#career-toggle').addEventListener('click', () => careerForm.classList.toggle('hidden'));
leadForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = leadForm.querySelector('button');
  button.disabled = true;
  const payload = Object.fromEntries(new FormData(leadForm));
  payload.conversation_id = conversationId || null;
  try {
    const response = await fetch('/api/leads', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to submit your enquiry.');
    leadStatus.textContent = 'Thank you. Our team will contact you soon.';
    leadForm.reset();
  } catch (error) { leadStatus.textContent = error.message; }
  finally { button.disabled = false; }
});

careerForm.addEventListener('submit', async event => {
  event.preventDefault();
  const button = careerForm.querySelector('button[type="submit"]');
  const formData = new FormData(careerForm);
  const resume = formData.get('resume');
  if (resume && resume.size > 5 * 1024 * 1024) {
    careerStatus.textContent = 'Resume must be no larger than 5 MB.';
    return;
  }
  if (conversationId) formData.set('conversation_id', conversationId);
  button.disabled = true;
  careerStatus.textContent = 'Submitting your application…';
  try {
    const response = await fetch('/api/careers/applications', {method: 'POST', body: formData});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Please check the application details and try again.');
    careerStatus.textContent = `Application submitted for HR review. Your reference is ${data.reference}. Please do not call other departments for recruitment updates.`;
    careerForm.reset();
  } catch (error) {
    careerStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
