// Run with: node --test tests/js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createQuizState, STORAGE_KEY } from '../../app/static/js/quiz-state.js';

function memoryStorage() {
  const data = new Map();
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

function answerAll(quiz, letters) {
  for (const l of letters) {
    quiz.answer(l);
    quiz.next();
  }
}

test('next requires an answer', () => {
  const quiz = createQuizState(memoryStorage());
  assert.equal(quiz.next(), false);
  assert.equal(quiz.index, 0);
  quiz.answer('B');
  assert.equal(quiz.next(), true);
  assert.equal(quiz.index, 1);
});

test('previous answers are preserved when navigating backward', () => {
  const quiz = createQuizState(memoryStorage());
  answerAll(quiz, ['A', 'B', 'C']);
  assert.equal(quiz.index, 3);
  quiz.back();
  assert.equal(quiz.current(), 'C');
  quiz.back();
  assert.equal(quiz.current(), 'B');
  quiz.back();
  assert.equal(quiz.current(), 'A');
  quiz.back(); // cannot go below the first question
  assert.equal(quiz.index, 0);
  assert.deepEqual(quiz.answers.slice(0, 3), ['A', 'B', 'C']);
});

test('reload restores answers, position and result without changing them', () => {
  const storage = memoryStorage();
  const quiz = createQuizState(storage);
  answerAll(quiz, ['D', 'D', 'D', 'A', 'A', 'A']);
  quiz.setResult('WIZARD');
  const reloaded = createQuizState(storage);
  assert.deepEqual(reloaded.answers, ['D', 'D', 'D', 'A', 'A', 'A']);
  assert.equal(reloaded.result, 'WIZARD');
  assert.equal(reloaded.index, 5);
  assert.ok(reloaded.isComplete());
});

test('retaking the quiz resets previous answers and result', () => {
  const storage = memoryStorage();
  const quiz = createQuizState(storage);
  answerAll(quiz, ['A', 'A', 'A', 'A', 'A', 'A']);
  quiz.setResult('WIZARD');
  quiz.reset();
  assert.deepEqual(quiz.answers, [null, null, null, null, null, null]);
  assert.equal(quiz.result, null);
  assert.equal(quiz.index, 0);
  assert.equal(createQuizState(storage).result, null);
});

test('changing an answer invalidates the old result; re-selecting the same one does not', () => {
  const quiz = createQuizState(memoryStorage());
  answerAll(quiz, ['A', 'A', 'A', 'A', 'A', 'A']);
  quiz.setResult('WIZARD');
  quiz.answer('A');
  assert.equal(quiz.result, 'WIZARD');
  quiz.back();
  quiz.answer('D');
  assert.equal(quiz.result, null);
});

test('corrupted storage starts a fresh quiz', () => {
  const storage = memoryStorage();
  storage.setItem(STORAGE_KEY, '{not json');
  const quiz = createQuizState(storage);
  assert.equal(quiz.index, 0);
  storage.setItem(STORAGE_KEY, JSON.stringify({ answers: ['X', 'A'], index: 9 }));
  assert.deepEqual(createQuizState(storage).answers, [null, null, null, null, null, null]);
});

test('invalid letters are rejected', () => {
  const quiz = createQuizState(memoryStorage());
  assert.throws(() => quiz.answer('E'));
});

test('works without any storage', () => {
  const quiz = createQuizState(null);
  quiz.answer('C');
  assert.equal(quiz.current(), 'C');
});
