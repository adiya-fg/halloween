// Quiz navigation state (no DOM access, so it can be unit-tested with `node --test`).
// Persisted in sessionStorage so Back/Next and page reloads never lose answers,
// and a stored result is re-used instead of being recomputed.

export const STORAGE_KEY = 'hw26:quiz';
export const LETTERS = ['A', 'B', 'C', 'D'];

function blank(total) {
  return { answers: Array(total).fill(null), index: 0, result: null };
}

export function createQuizState(storage, total = 6) {
  let state = blank(total);
  try {
    const saved = storage && JSON.parse(storage.getItem(STORAGE_KEY) || 'null');
    if (saved && Array.isArray(saved.answers) && saved.answers.length === total) {
      state = {
        answers: saved.answers.map((a) => (LETTERS.includes(a) ? a : null)),
        index: Math.min(Math.max(0, saved.index | 0), total - 1),
        result: saved.result || null,
      };
    }
  } catch (e) { /* corrupted or unavailable storage: start fresh */ }

  function save() {
    try { storage && storage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch (e) { /* ignore */ }
  }

  return {
    get total() { return total; },
    get index() { return state.index; },
    get answers() { return state.answers.slice(); },
    get result() { return state.result; },
    current() { return state.answers[state.index]; },
    isComplete() { return state.answers.every((a) => a !== null); },
    isLast() { return state.index === total - 1; },

    /** Select an answer for the current question. Changing an answer invalidates any old result. */
    answer(letter) {
      if (!LETTERS.includes(letter)) throw new Error('invalid answer');
      if (state.answers[state.index] !== letter) state.result = null;
      state.answers[state.index] = letter;
      save();
    },
    /** Move forward only when the current question is answered. */
    next() {
      if (state.answers[state.index] === null) return false;
      if (state.index < total - 1) state.index += 1;
      save();
      return true;
    },
    back() {
      if (state.index > 0) state.index -= 1;
      save();
    },
    setResult(result) {
      state.result = result;
      save();
    },
    /** "Try again": forget everything. */
    reset() {
      state = blank(total);
      save();
    },
  };
}
