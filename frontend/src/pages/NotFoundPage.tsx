import { Link } from 'react-router-dom';
import { useAuth } from '../auth/useAuth';

/**
 * Any address the app has no route for. Written as one line on a transcript,
 * because that's the document every student here already knows how to read,
 * and it turns "you followed a bad link" into a small joke instead of an
 * error. It still has to get them somewhere (DESIGN.md, "never a dead end"),
 * so a signed-in student gets their Overview and the chat; anyone else gets
 * sign-in, since both of those would bounce them there anyway.
 */
export function NotFoundPage() {
  const { session, profile } = useAuth();
  const signedIn = Boolean(session || profile);

  return (
    <main className="not-found">
      <div className="not-found-brand">
        <span className="not-found-mark" aria-hidden="true" />
        <span translate="no">GradusIQ</span>
      </div>
      <section className="card not-found-card" aria-labelledby="not-found-title">
        <div className="not-found-sheet-head">
          <span>Unofficial transcript</span>
          <span>Term: Lost</span>
        </div>
        <table className="not-found-line">
          <caption className="sr-only">The missing page, as a transcript line</caption>
          <thead>
            <tr>
              <th scope="col">Course</th>
              <th scope="col">Title</th>
              <th scope="col" className="not-found-num">Credits</th>
              <th scope="col" className="not-found-num">Grade</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="not-found-code">PAGE 404</td>
              <td>Page Not Found</td>
              <td className="not-found-num">0.0</td>
              <td className="not-found-num">W</td>
            </tr>
          </tbody>
        </table>
        <p className="not-found-prereq">Prerequisite: a valid link.</p>

        <h1 id="not-found-title" className="not-found-title">This page isn't on your transcript.</h1>
        <p className="not-found-body">
          The link may be old or mistyped. Nothing on your record has changed.
        </p>
        <div className="not-found-actions">
          {signedIn ? (
            <>
              <Link to="/dashboard" className="btn btn-primary">Back to Overview</Link>
              <Link to="/dashboard" state={{ ask: true }} className="btn btn-secondary">Ask GradusIQ</Link>
            </>
          ) : (
            <Link to="/login" className="btn btn-primary">Go to sign in</Link>
          )}
        </div>
      </section>
    </main>
  );
}
