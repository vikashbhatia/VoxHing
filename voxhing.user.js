// ==UserScript==
// @name         VoxHing — Local Whisper Voice Typing
// @namespace    https://vikashbhatia.in/
// @version      1.0.0
// @description  Local Whisper-powered Hinglish, Hindi and English voice typing for text fields on the web.
// @homepageURL  https://github.com/vikashbhatia/VoxHing
// @supportURL   https://github.com/vikashbhatia/VoxHing/issues
// @updateURL    https://raw.githubusercontent.com/vikashbhatia/VoxHing/main/voxhing.user.js
// @downloadURL  https://raw.githubusercontent.com/vikashbhatia/VoxHing/main/voxhing.user.js
// @match        *://*/*
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @connect      localhost
// ==/UserScript==

(function () {
    'use strict';

    const API = 'http://127.0.0.1:8765';
    const TOKEN = 'vikash-local-whisper-v1';
    const MODES = ['HING', 'HI', 'EN'];

    let mode = localStorage.getItem('__voxhing_mode') || 'HING';
    if (!MODES.includes(mode)) mode = 'HING';

    let currentField = null;
    let micField = null;
    let recordingField = null;
    let savedCaret = null;
    let recording = false;
    let transcribing = false;
    let pollTimer = null;
    let soloShift = false;
    let actionAfterDone = null;
    const caretMemory = new WeakMap();

    const box = document.createElement('div');
    Object.assign(box.style, {
        position: 'fixed', display: 'none', height: '32px', alignItems: 'center',
        borderRadius: '16px', overflow: 'hidden', background: '#fff',
        boxShadow: '0 1px 8px rgba(0,0,0,.30)', zIndex: '2147483647',
        fontFamily: 'Arial,sans-serif', userSelect: 'none'
    });

    const mic = document.createElement('button');
    mic.type = 'button';
    mic.tabIndex = 0;
    Object.assign(mic.style, {
        width: '35px', height: '32px', border: '0', padding: '0', margin: '0',
        background: '#fff', cursor: 'pointer', fontSize: '16px', outline: 'none'
    });

    const modeBtn = document.createElement('button');
    modeBtn.type = 'button';
    modeBtn.tabIndex = -1;
    Object.assign(modeBtn.style, {
        height: '32px', minWidth: '44px', border: '0', borderLeft: '1px solid #ddd',
        padding: '0 7px', margin: '0', cursor: 'pointer', fontSize: '10px',
        fontWeight: '700', outline: 'none'
    });

    box.append(mic, modeBtn);
    (document.body || document.documentElement).appendChild(box);
    box.addEventListener('pointerdown', e => { e.preventDefault(); e.stopPropagation(); });
    box.addEventListener('mousedown', e => { e.preventDefault(); e.stopPropagation(); });

    function paint() {
        modeBtn.textContent = mode;
        const palette = mode === 'HING'
            ? ['#e8f5e9', '#137333']
            : mode === 'HI' ? ['#fff3e0', '#a45100'] : ['#e8f0fe', '#174ea6'];
        modeBtn.style.background = palette[0];
        modeBtn.style.color = palette[1];

        if (recording) {
            mic.textContent = '■'; mic.style.background = '#e53935'; mic.style.color = '#fff';
            mic.title = 'Recording — Space stops';
        } else if (transcribing) {
            mic.textContent = '…'; mic.style.background = '#1976d2'; mic.style.color = '#fff';
            mic.title = 'Whisper is transcribing...';
        } else {
            mic.textContent = '🎤'; mic.style.background = '#fff'; mic.style.color = '#000';
            mic.title = 'Space: record • Left: field • Shift: next field';
        }
    }

    modeBtn.addEventListener('click', e => {
        e.preventDefault(); e.stopPropagation();
        if (recording || transcribing) return;
        mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
        localStorage.setItem('__voxhing_mode', mode);
        paint(); position();
    });

    function api(method, path, body = null) {
        return new Promise((resolve, reject) => {
            GM_xmlhttpRequest({
                method,
                url: API + path,
                headers: {
                    'X-Voice-Token': TOKEN,
                    ...(body ? { 'Content-Type': 'application/json' } : {})
                },
                data: body ? JSON.stringify(body) : undefined,
                timeout: 6000,
                onload: res => {
                    let data;
                    try { data = JSON.parse(res.responseText || '{}'); }
                    catch (_) { data = { detail: res.responseText }; }
                    if (res.status >= 200 && res.status < 300) resolve(data);
                    else reject(new Error(data.detail || `HTTP ${res.status}`));
                },
                onerror: () => reject(new Error('VoxHing server is not running. Start start_voice_server.bat.')),
                ontimeout: () => reject(new Error('VoxHing local server timed out.'))
            });
        });
    }

    function editable(el) {
        if (!el || el.nodeType !== 1) return false;
        if (el instanceof HTMLInputElement) {
            return ['text', 'search', 'email', 'url', 'tel'].includes((el.type || 'text').toLowerCase())
                && !el.disabled && !el.readOnly;
        }
        if (el instanceof HTMLTextAreaElement) return !el.disabled && !el.readOnly;
        if (el.isContentEditable) return true;
        return el.getAttribute?.('role') === 'textbox' && el.getAttribute('aria-disabled') !== 'true';
    }

    function fieldFrom(el) {
        if (!el || el.nodeType !== 1) return null;
        if (editable(el)) return el;
        try {
            const p = el.closest(
                'input[type="text"],input[type="search"],input[type="email"],input[type="url"],input[type="tel"],textarea,' +
                '[contenteditable="true"],[contenteditable="plaintext-only"],[role="textbox"]'
            );
            return p && editable(p) ? p : null;
        } catch (_) { return null; }
    }

    function usable(field) {
        if (!field || !field.isConnected) return false;
        const r = field.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
    }

    function fields() {
        const selector =
            'input[type="text"],input[type="search"],input[type="email"],input[type="url"],input[type="tel"],textarea,' +
            '[contenteditable="true"],[contenteditable="plaintext-only"],[role="textbox"]';
        const out = [], seen = new Set();
        document.querySelectorAll(selector).forEach(el => {
            const f = fieldFrom(el);
            if (f && !seen.has(f) && usable(f)) { seen.add(f); out.push(f); }
        });
        return out;
    }

    function nextField(after) {
        const list = fields();
        if (!list.length) return null;
        const i = list.indexOf(after);
        return i < 0 ? list[0] : list[(i + 1) % list.length];
    }

    function capture(field) {
        if (!field) return null;
        if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
            const p = {
                start: field.selectionStart ?? field.value.length,
                end: field.selectionEnd ?? field.value.length
            };
            caretMemory.set(field, p);
            return p;
        }
        const s = window.getSelection();
        if (s?.rangeCount) {
            const r = s.getRangeAt(0);
            if (field.contains(r.commonAncestorContainer)) {
                const p = { range: r.cloneRange() };
                caretMemory.set(field, p);
                return p;
            }
        }
        return caretMemory.get(field) || null;
    }

    function restore(field, saved = null) {
        const p = saved || caretMemory.get(field);
        try { field.focus({ preventScroll: true }); } catch (_) { field.focus(); }

        if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
            const n = field.value.length;
            const a = Math.min(p?.start ?? n, n);
            const b = Math.min(p?.end ?? a, n);
            try { field.setSelectionRange(a, b); } catch (_) {}
            return;
        }

        const s = window.getSelection();
        if (!s) return;
        try {
            s.removeAllRanges();
            if (p?.range && field.contains(p.range.commonAncestorContainer)) s.addRange(p.range);
            else {
                const r = document.createRange();
                r.selectNodeContents(field); r.collapse(false); s.addRange(r);
            }
        } catch (_) {}
    }

    function show(field) {
        if (!usable(field)) return;
        currentField = micField = field;
        capture(field); position();
        box.style.display = 'flex';
    }

    function position() {
        const field = micField || currentField;
        if (!usable(field)) { box.style.display = 'none'; return; }
        const r = field.getBoundingClientRect();
        const w = mode === 'HING' ? 80 : 68;
        const h = 32;
        let left = r.right - w - 5;
        let top = r.top + Math.max(2, (r.height - h) / 2);
        if (field instanceof HTMLTextAreaElement || field.isContentEditable || field.getAttribute?.('role') === 'textbox') {
            top = r.top + 5;
        }
        if (r.width < w + 15) left = r.right + 4;
        left = Math.max(4, Math.min(left, innerWidth - w - 4));
        top = Math.max(4, Math.min(top, innerHeight - h - 4));
        box.style.left = `${Math.round(left)}px`;
        box.style.top = `${Math.round(top)}px`;
        box.style.display = 'flex';
    }

    window.addEventListener('resize', position);
    window.addEventListener('scroll', position, true);

    document.addEventListener('pointerdown', e => {
        if (box.contains(e.target)) return;
        const path = e.composedPath ? e.composedPath() : [e.target];
        let f = null;
        for (const node of path) {
            if (node?.nodeType === 1 && (f = fieldFrom(node))) break;
        }
        if (f) {
            show(f);
            setTimeout(() => { capture(f); show(f); }, 25);
        } else if (!recording && !transcribing && document.activeElement !== mic) {
            box.style.display = 'none';
        }
    }, true);

    document.addEventListener('focusin', e => {
        if (e.target === mic || e.target === modeBtn) return;
        const f = fieldFrom(e.target);
        if (f) show(f);
    }, true);

    function fieldContext(field) {
        if (!field) return '';
        return [
            field.getAttribute?.('placeholder'),
            field.getAttribute?.('aria-label'),
            field.getAttribute?.('name')
        ].filter(Boolean).join(' ').slice(0, 140);
    }

    async function start() {
        if (recording || transcribing || !micField) return;
        recordingField = micField;
        savedCaret = capture(recordingField);
        actionAfterDone = null;
        try {
            await api('POST', '/start', { mode, context: fieldContext(recordingField) });
            recording = true; transcribing = false; paint();
            beginPolling();
        } catch (err) {
            recording = transcribing = false; paint();
            toast(err.message, true);
        }
    }

    async function stop() {
        if (!recording) return;
        try {
            await api('POST', '/stop');
            recording = false; transcribing = true; paint();
        } catch (err) { toast(err.message, true); }
    }

    function beginPolling() {
        clearInterval(pollTimer);
        pollTimer = setInterval(async () => {
            try {
                const s = await api('GET', '/status');
                if (s.state === 'recording' || s.state === 'starting') {
                    recording = true; transcribing = false; paint(); return;
                }
                if (s.state === 'transcribing') {
                    recording = false; transcribing = true; paint(); return;
                }
                if (s.state === 'error') {
                    finishPolling(); toast(s.error || 'Whisper transcription failed.', true); return;
                }
                if (s.state === 'done') {
                    finishPolling();
                    if (s.text) insert(recordingField, s.text, savedCaret);
                    else toast('No speech detected.');
                    completeNavigation();
                }
            } catch (err) {
                finishPolling(); toast(err.message, true);
            }
        }, 220);
    }

    function finishPolling() {
        clearInterval(pollTimer); pollTimer = null;
        recording = false; transcribing = false; paint();
    }

    function completeNavigation() {
        const field = recordingField;
        const action = actionAfterDone;
        recordingField = savedCaret = actionAfterDone = null;

        if (action === 'next') {
            const n = nextField(field); if (n) focusField(n); return;
        }
        if (action === 'field') {
            if (field) focusField(field); return;
        }
        if (field) {
            currentField = micField = field; position();
            try { mic.focus({ preventScroll: true }); } catch (_) { mic.focus(); }
        }
    }

    function toggle() {
        if (transcribing) return;
        if (recording) stop(); else start();
    }

    function nativeSet(el, value) {
        const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        const descriptor = Object.getOwnPropertyDescriptor(proto, 'value');
        if (descriptor?.set) descriptor.set.call(el, value); else el.value = value;
    }

    function fireInput(el, data) {
        try {
            el.dispatchEvent(new InputEvent('input', {
                bubbles: true, composed: true, inputType: 'insertText', data
            }));
        } catch (_) {
            el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
        }
    }

    function insert(field, text, saved) {
        if (!field?.isConnected) return;
        restore(field, saved);

        if (field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement) {
            const old = field.value || '';
            const a = Math.min(saved?.start ?? field.selectionStart ?? old.length, old.length);
            const b = Math.min(saved?.end ?? field.selectionEnd ?? a, old.length);
            let value = text.trim();
            if (a > 0 && old[a - 1] && !/\s/.test(old[a - 1])) value = ' ' + value;
            if (b < old.length && old[b] && !/\s/.test(old[b])) value += ' ';
            nativeSet(field, old.slice(0, a) + value + old.slice(b));
            const pos = a + value.length;
            try { field.setSelectionRange(pos, pos); } catch (_) {}
            fireInput(field, value); capture(field); return;
        }

        let ok = false;
        try { ok = document.execCommand('insertText', false, text); } catch (_) {}
        if (!ok) {
            const s = window.getSelection();
            if (s?.rangeCount) {
                const r = s.getRangeAt(0); r.deleteContents();
                const n = document.createTextNode(text); r.insertNode(n); r.setStartAfter(n); r.collapse(true);
                s.removeAllRanges(); s.addRange(r);
            } else field.appendChild(document.createTextNode(text));
            fireInput(field, text);
        }
        capture(field);
    }

    function focusField(field) {
        if (!field?.isConnected) return;
        currentField = micField = field;
        restore(field); position();
    }

    function focusMic(field) {
        if (!field?.isConnected) return;
        capture(field); currentField = micField = field; position();
        try { mic.focus({ preventScroll: true }); } catch (_) { mic.focus(); }
    }

    function soloShiftAction() {
        if (document.activeElement === mic) {
            if (recording || transcribing) {
                actionAfterDone = 'next';
                if (recording) stop();
            } else {
                const n = nextField(micField); if (n) focusField(n);
            }
            return;
        }
        const f = fieldFrom(document.activeElement);
        if (f) { focusMic(f); return; }
        if (currentField) { focusMic(currentField); return; }
        const first = fields()[0]; if (first) focusField(first);
    }

    document.addEventListener('keydown', e => {
        if (e.key === 'Shift') {
            if (!e.repeat) soloShift = true;
            return;
        }
        if (e.shiftKey) soloShift = false;
    }, true);

    document.addEventListener('keyup', e => {
        if (e.key !== 'Shift') return;
        const go = soloShift && !e.ctrlKey && !e.altKey && !e.metaKey;
        soloShift = false;
        if (!go) return;
        e.preventDefault(); e.stopPropagation(); soloShiftAction();
    }, true);

    mic.addEventListener('keydown', e => {
        if (e.code === 'Space' || e.key === ' ') {
            e.preventDefault(); e.stopPropagation(); toggle(); return;
        }
        if (e.key === 'ArrowLeft' || e.key === 'Escape') {
            e.preventDefault(); e.stopPropagation();
            if (recording || transcribing) {
                actionAfterDone = 'field';
                if (recording) stop();
            } else if (micField) focusField(micField);
        }
    });

    mic.addEventListener('click', e => {
        e.preventDefault(); e.stopPropagation();
        try { mic.focus({ preventScroll: true }); } catch (_) { mic.focus(); }
        toggle();
    });

    let toastTimer = null;
    function toast(message, error = false) {
        let t = document.getElementById('__voxhing_toast');
        if (!t) {
            t = document.createElement('div');
            t.id = '__voxhing_toast';
            Object.assign(t.style, {
                position: 'fixed', left: '50%', bottom: '25px', transform: 'translateX(-50%)',
                maxWidth: '650px', padding: '10px 16px', borderRadius: '8px', color: '#fff',
                font: '14px Arial,sans-serif', zIndex: '2147483647', pointerEvents: 'none',
                boxShadow: '0 2px 12px rgba(0,0,0,.3)', textAlign: 'center'
            });
            document.documentElement.appendChild(t);
        }
        t.textContent = message;
        t.style.background = error ? '#c62828' : '#222';
        t.style.display = 'block';
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { t.style.display = 'none'; }, 3500);
    }

    paint();
})();
