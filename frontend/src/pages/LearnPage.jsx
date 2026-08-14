import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { LESSONS, loadProgress, saveProgress } from '../lib/curriculum.js';

export default function LearnPage() {
  const navigate = useNavigate();
  const [progress, setProgress] = useState(() => loadProgress());
  const [openId, setOpenId] = useState(null);

  const completed = useMemo(
    () => LESSONS.filter((l) => progress[l.id]?.done).length,
    [progress]
  );

  const markDone = (id) => {
    const next = { ...progress, [id]: { ...(progress[id] || {}), done: true } };
    setProgress(next);
    saveProgress(next);
  };
  const recordQuiz = (id, correct) => {
    const next = { ...progress, [id]: { ...(progress[id] || {}), quiz: correct, done: true } };
    setProgress(next);
    saveProgress(next);
  };

  return (
    <div className="rh-page">
      <div className="rh-card">
        <div className="rh-label">Your progress</div>
        <div className="rh-hero-value">{completed}/{LESSONS.length}</div>
        <div className="rh-progressbar"><span style={{ width: `${(completed / LESSONS.length) * 100}%` }} /></div>
        <p className="rh-lead" style={{ marginTop: 8 }}>Complete lessons and pass the checks to build a foundation before you risk real money.</p>
      </div>

      <button className="rh-row" onClick={() => navigate('/methodology')}>
        <div className="rh-col">
          <span className="rh-sym">📊 Methodology &amp; Data</span>
          <span className="rh-name">What the strategy is trained on + our honest audit findings</span>
        </div>
        <span className="rh-pill">Open →</span>
      </button>

      {LESSONS.map((lesson) => {
        const p = progress[lesson.id] || {};
        const open = openId === lesson.id;
        return (
          <div key={lesson.id} className="rh-card">
            <div className="rh-inline" style={{ justifyContent: 'space-between', cursor: 'pointer' }} onClick={() => setOpenId(open ? null : lesson.id)}>
              <div>
                <h4 style={{ marginBottom: 4 }}>{lesson.title}</h4>
                <span className="rh-name" style={{ color: 'var(--muted)' }}>{lesson.minutes} min read</span>
              </div>
              <span className={`rh-pill${p.done ? ' done' : ''}`}>{p.done ? '✓ Done' : 'Start'}</span>
            </div>

            {open && (
              <div style={{ marginTop: 12 }}>
                <LessonBody text={lesson.body} />
                <Quiz lesson={lesson} saved={p.quiz} onAnswer={(ok) => recordQuiz(lesson.id, ok)} />
                {!p.done && (
                  <button className="rh-btn secondary sm block" style={{ marginTop: 10 }} onClick={() => markDone(lesson.id)}>
                    Mark as read
                  </button>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function LessonBody({ text }) {
  const paras = text.split(/\n\n+/);
  const render = (s) => {
    // minimal **bold** support
    const parts = s.split(/(\*\*[^*]+\*\*)/g);
    return parts.map((part, i) =>
      part.startsWith('**') && part.endsWith('**')
        ? <strong key={i}>{part.slice(2, -2)}</strong>
        : <React.Fragment key={i}>{part}</React.Fragment>
    );
  };
  return (
    <div className="rh-lesson-body">
      {paras.map((p, i) => <p key={i}>{render(p)}</p>)}
    </div>
  );
}

function Quiz({ lesson, saved, onAnswer }) {
  const [picked, setPicked] = useState(saved != null ? -2 : null);
  const q = lesson.quiz;
  const answered = picked != null && picked !== -2;
  const done = picked === -2 || answered;

  const choose = (i) => {
    if (done) return;
    setPicked(i);
    onAnswer(i === q.answer);
  };

  return (
    <div style={{ marginTop: 14 }}>
      <div className="rh-label" style={{ marginBottom: 8 }}>Knowledge check</div>
      <p style={{ fontWeight: 600, margin: '0 0 10px' }}>{q.question}</p>
      {q.options.map((opt, i) => {
        let cls = 'rh-quiz-opt';
        if (answered) {
          if (i === q.answer) cls += ' correct';
          else if (i === picked) cls += ' wrong';
        }
        return (
          <button key={i} className={cls} onClick={() => choose(i)} disabled={done}>
            {opt}
          </button>
        );
      })}
      {answered && (
        <p className="rh-lead" style={{ marginTop: 8 }}>
          {picked === q.answer ? '✅ Correct. ' : '❌ Not quite. '}{q.explain}
        </p>
      )}
      {picked === -2 && <p className="rh-lead" style={{ marginTop: 8 }}>You already completed this check.</p>}
    </div>
  );
}
