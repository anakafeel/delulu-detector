// "How this is calculated": the whole scoring math, in plain words. Opened with
// the ? key (or the header button); Esc or ? closes it, and it closes itself when
// a round starts so it never covers the live read. Say what the numbers are and
// nothing more: no claim this measures interview skill, honesty or nerves.
export default function HowItWorks({ onClose }) {
  return (
    <div
      className="anim-fade-in fixed inset-0 z-[60] flex items-center justify-center bg-void/85 p-8"
      role="dialog"
      aria-modal="true"
      aria-labelledby="how-title"
      onClick={onClose}
    >
      <div
        className="w-[min(60rem,100%)] rounded-2xl border border-ink-faint/60 bg-surface px-10 py-8"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="how-title" className="font-display text-title text-ink">
          How this is calculated
        </h2>

        <dl className="mt-6 grid grid-cols-[auto_1fr] gap-x-8 gap-y-5 font-game text-data text-ink-dim">
          <dt className="font-bold text-claim">Claim</dt>
          <dd>The number you dialed in, 0 to 100, before the question. Your guess at how unreadable your face is.</dd>

          <dt className="font-bold text-reality">Composure</dt>
          <dd>
            While the question plays, Presage software reads your face from the webcam, frame by frame, and rates
            how neutral your expression looks, 0 to 100. Your composure is the average over the window. Frames are
            not saved, except one photo if you said yes to it, kept in this laptop's memory for the
            leaderboard and gone when the game stops.
          </dd>

          <dt className="font-bold text-ink">Gap</dt>
          <dd>The difference between the two: |claim − composure|. Too high or too low counts the same.</dd>

          <dt className="font-bold text-ink">Score</dt>
          <dd>100 − gap. A perfect guess about your own face scores 100.</dd>
        </dl>

        <p className="mt-6 border-t border-ink-faint/40 pt-5 font-game text-meta text-ink-dim">
          That's all of it. It reads your expression for a few seconds. It's not a lie detector, and it doesn't say
          anything about how you'd do in a real interview.
        </p>
        <p className="mt-3 font-game text-meta text-ink-faint">Press ? or Esc to close.</p>
      </div>
    </div>
  )
}
