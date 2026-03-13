// Nagarik — Civic Escalation Engine
// backend/services/civicEscalationEngine.js

import { CIVIC_CATEGORIES } from '../config/civicCategories.js';

export const computeUrgencyScore = ({ sla_hours, created_at, duplicate_count = 0, upvote_count = 0 }) => {
  const hoursElapsed = (Date.now() - new Date(created_at)) / 3_600_000;
  const slaRatio     = Math.min(hoursElapsed / sla_hours, 2);
  const slaScore     = slaRatio * 50;
  const dupScore     = Math.min(duplicate_count * 7, 35);
  const upvoteScore  = Math.min(upvote_count * 1.5, 15);
  return Math.round(Math.min(slaScore + dupScore + upvoteScore, 100));
};

export const getEscalationLevel = ({ category_id, created_at }) => {
  const category = CIVIC_CATEGORIES.find((c) => c.id === category_id);
  if (!category) return { level: 'L1', role: 'Ward Officer' };
  const hoursElapsed = (Date.now() - new Date(created_at)) / 3_600_000;
  const { sla_hours, escalation } = category;
  if (hoursElapsed > sla_hours * 2) return { level: 'L3', ...escalation.L3 };
  if (hoursElapsed > sla_hours)     return { level: 'L2', ...escalation.L2 };
  return                                    { level: 'L1', ...escalation.L1 };
};

export const checkAndEscalate = async (issue, db, notifier) => {
  const currentLevel = getEscalationLevel(issue);
  if (currentLevel.level === issue.escalation_level) return null;

  const event = {
    issue_id:     issue.id,
    from_level:   issue.escalation_level,
    to_level:     currentLevel.level,
    to_role:      currentLevel.role,
    escalated_at: new Date().toISOString(),
    reason:       `SLA breached — auto-escalated to ${currentLevel.role}`,
  };

  await db.escalationLogs.insert(event);
  await db.issues.update(issue.id, { escalation_level: currentLevel.level });

  await notifier.send({
    to:      issue.reporter_contact,
    channel: 'whatsapp',
    message: `Update on your Nagarik issue #${issue.id}: escalated to ${currentLevel.role} due to delay.`,
  });

  const assigneeEmail = currentLevel.notify?.replace('{city}', issue.city_id);
  if (assigneeEmail) {
    await notifier.sendEmail({
      to:      assigneeEmail,
      subject: `[Nagarik] Escalated Issue #${issue.id} — Action Required`,
      body:    `Issue #${issue.id} has been escalated. View: https://nagarik.care/issue/${issue.id}`,
    });
  }
  return event;
};

export const runEscalationCron = async (db, notifier) => {
  const openIssues = await db.issues.findAll({ status: { $in: ['open', 'in_progress'] } });
  const results = await Promise.allSettled(
    openIssues.map((issue) => checkAndEscalate(issue, db, notifier))
  );
  const escalated = results.filter((r) => r.status === 'fulfilled' && r.value).length;
  console.log(`[Nagarik Escalation Cron] Checked ${openIssues.length}. Escalated: ${escalated}`);
  return { checked: openIssues.length, escalated };
};
