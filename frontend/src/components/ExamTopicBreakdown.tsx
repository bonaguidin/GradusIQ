import type { Assignment, ExamTopicTags, ExamTopicTag } from '../types/student';

interface ExamTopicBreakdownProps {
  assignments: Assignment[];
  examTopicTags: ExamTopicTags;
}

function TopicBar({ tag }: { tag: ExamTopicTag }) {
  const pct = tag.max_score > 0 ? (tag.score / tag.max_score) * 100 : 0;
  return (
    <div className="topic-bar-row">
      <span className="topic-label">{tag.topic}</span>
      <div
        className="topic-bar"
        role="progressbar"
        aria-valuenow={tag.score}
        aria-valuemin={0}
        aria-valuemax={tag.max_score}
        aria-label={`${tag.topic}: ${tag.score}/${tag.max_score}`}
      >
        <div
          className="topic-bar-fill"
          style={{ transform: `scaleX(${pct / 100})` }}
        />
      </div>
      <span className="topic-score">
        {tag.score}/{tag.max_score}
      </span>
    </div>
  );
}

export function ExamTopicBreakdown({ assignments, examTopicTags }: ExamTopicBreakdownProps) {
  if (!examTopicTags || Object.keys(examTopicTags).length === 0) {
    return <p className="empty-state">No exam topic data available.</p>;
  }

  const assignmentById = new Map<number, Assignment>();
  for (const a of assignments) assignmentById.set(a.id, a);

  const tagEntries = Object.entries(examTopicTags);

  // Group topics by topic name within each assignment for bar chart grouping
  return (
    <div className="exam-breakdown">
      {tagEntries.map(([assignmentIdStr, tags]) => {
        const assignmentId = parseInt(assignmentIdStr, 10);
        const assignment = assignmentById.get(assignmentId);
        const assignmentName = assignment?.name ?? `Assignment ${assignmentIdStr}`;

        if (!tags || tags.length === 0) return null;

        // Aggregate tags by topic (sum scores/max)
        const topicMap = new Map<string, { score: number; max_score: number; question_id: string }>();
        for (const tag of tags) {
          const existing = topicMap.get(tag.topic);
          if (existing) {
            existing.score += tag.score;
            existing.max_score += tag.max_score;
          } else {
            topicMap.set(tag.topic, {
              score: tag.score,
              max_score: tag.max_score,
              question_id: tag.question_id,
            });
          }
        }

        const aggregatedTags: ExamTopicTag[] = Array.from(topicMap.entries()).map(
          ([topic, data]) => ({
            question_id: data.question_id,
            topic,
            score: data.score,
            max_score: data.max_score,
          }),
        );

        return (
          <div key={assignmentIdStr} className="exam-assignment">
            <h4 className="exam-assignment-name">{assignmentName}</h4>
            <div className="topic-bars">
              {aggregatedTags.map((tag) => (
                <TopicBar key={tag.topic} tag={tag} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
