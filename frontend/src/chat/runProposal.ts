// Carries out a change the assistant proposed (backend ai/chat_changes.py),
// after the student pressed Confirm on its card. Each kind calls the same
// endpoint its page uses, with the student's own session, so the server's
// usual checks apply exactly as if the student had done it on that page.

import type { ChatProposal } from '../api/chat';
import { fetchCanvasCalendar } from '../api/canvasCalendar';
import { addPlannedCourse, removePlannedCourse } from '../api/planning';
import { updateProfile } from '../api/profile';
import { notifyDataChanged } from '../lib/dataChanged';

export interface ProposalOutcome {
  ok: boolean;
  /** What happened, in the student's words, or why it did not. */
  message: string;
}

export async function runProposal(
  accessToken: string,
  proposal: ChatProposal,
  reloadProfile: () => Promise<void>,
): Promise<ProposalOutcome> {
  const identity = { slug: null, accessToken };
  const payload = proposal.payload;
  switch (proposal.kind) {
    case 'add_planned_course': {
      const result = await addPlannedCourse(identity, {
        course_code: String(payload.course_code),
        year: Number(payload.year),
        season: String(payload.season),
        title: typeof payload.title === 'string' ? payload.title : undefined,
        credit_hours: typeof payload.credit_hours === 'number' ? payload.credit_hours : undefined,
        catalog_course_id: typeof payload.catalog_course_id === 'string' ? payload.catalog_course_id : undefined,
      });
      if (!result.ok) return { ok: false, message: result.message ?? 'Could not add that course.' };
      notifyDataChanged('planned-courses');
      const term = `${String(payload.season)} ${String(payload.year)}`;
      // A term that has already started takes the course as in progress
      // (lifecycle.add_course_respecting_activation), so say so.
      return result.course?.kind === 'in_progress'
        ? { ok: true, message: `Added ${String(payload.course_code)} to ${term} as in progress.` }
        : { ok: true, message: `Added ${String(payload.course_code)} to your ${term} plan.` };
    }
    case 'remove_planned_course': {
      const result = await removePlannedCourse(identity, String(payload.planned_id));
      if (!result.ok) return { ok: false, message: 'Could not remove that course.' };
      notifyDataChanged('planned-courses');
      return { ok: true, message: 'Removed from your plan.' };
    }
    case 'add_target_role': {
      const roles = Array.isArray(payload.target_roles) ? payload.target_roles.map(String) : [];
      try {
        await updateProfile(accessToken, { target_roles: roles });
      } catch (e) {
        return { ok: false, message: e instanceof Error ? e.message : 'Could not update your target roles.' };
      }
      await reloadProfile();
      return { ok: true, message: `Target roles: ${roles.join(', ')}.` };
    }
    case 'refresh_canvas': {
      const result = await fetchCanvasCalendar(accessToken, true);
      if (!result.ok) return { ok: false, message: 'Canvas could not be refreshed. Try again from the calendar card.' };
      notifyDataChanged('canvas-calendar');
      return { ok: true, message: 'Canvas calendar refreshed.' };
    }
    default:
      return { ok: false, message: 'This change is not supported.' };
  }
}
