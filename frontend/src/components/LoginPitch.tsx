const POINTS = [
  'Degree progress read from your own transcript',
  'Role fit and skill gaps from your resume',
  'Courses that build toward the roles you want',
];

/**
 * The left half of the sign-in and sign-up screens on wide windows: what
 * GradusIQ is, in one line and three points, beside the form. Hidden below
 * 900px, where the form alone fills the screen.
 */
export function LoginPitch() {
  return (
    <aside className="login-pitch" aria-label="About GradusIQ">
      <p className="login-pitch-eyebrow">GradusIQ</p>
      <p className="login-pitch-title">Your academic record and career goals, read together.</p>
      <ul className="login-pitch-points">
        {POINTS.map((point) => (
          <li key={point}>{point}</li>
        ))}
      </ul>
    </aside>
  );
}
