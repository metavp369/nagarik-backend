// Nagarik — WhatsApp Bot Webhook
// backend/routes/whatsapp.js

import express from 'express';
import crypto from 'crypto';
import { CIVIC_CATEGORIES, getCategoryByKeyword } from '../config/civicCategories.js';
import { createIssue } from '../services/issueService.js';
import { sendWhatsApp } from '../services/whatsappSender.js';
import { classifyImageWithGPT } from '../services/aiClassifier.js';
import { transcribeAudio } from '../services/whisperService.js';

const router = express.Router();
const sessions = new Map();

const getSession  = (phone) => sessions.get(phone) || { step: 'idle' };
const setSession  = (phone, data) => sessions.set(phone, { ...getSession(phone), ...data });
const clearSession = (phone) => sessions.delete(phone);
const hashPhone   = (phone) => crypto.createHash('sha256').update(phone).digest('hex');

router.post('/incoming', async (req, res) => {
  res.sendStatus(200);
  const { phone, type, text, imageUrl, audioUrl, latitude, longitude } = parseIncoming(req.body);
  if (!phone) return;
  const session = getSession(phone);

  try {
    if (type === 'image') {
      setSession(phone, { step: 'awaiting_location', imageUrl });
      classifyImageWithGPT(imageUrl).then((r) => setSession(phone, { aiCategory: r.category }));
      await sendWhatsApp(phone,
        `Namaskar! I received your photo.\n\nWhere is this issue?\n?? Share location or type area (e.g. "Andheri East, Mumbai")`
      );
      return;
    }

    if (session.step === 'awaiting_location') {
      const location = type === 'location' ? { lat: latitude, lng: longitude } : { address: text };
      const sess = getSession(phone);
      const category = sess.aiCategory
        ? CIVIC_CATEGORIES.find((c) => c.id === sess.aiCategory)
        : getCategoryByKeyword(text || '');
      setSession(phone, { step: 'awaiting_confirmation', location, confirmedCategory: category?.id || 'general' });
      await sendWhatsApp(phone,
        `Got it!\n\n?? Category: ${category?.label || 'General Issue'}\n?? Location: ${location.address || `${latitude}, ${longitude}`}\n\nReply *1* to submit ?\nReply *2* to change category ??`
      );
      return;
    }

    if (session.step === 'awaiting_confirmation') {
      if (text === '1' || text?.toLowerCase() === 'yes') {
        const sess = getSession(phone);
        const issue = await createIssue({
          category_id:   sess.confirmedCategory,
          location:      sess.location,
          photo_url:     sess.imageUrl,
          reporter_hash: hashPhone(phone),
          reporter_phone: phone,
          source:        'whatsapp',
        });
        clearSession(phone);
        await sendWhatsApp(phone,
          `? Reported!\n\nIssue ID: #NGK-${issue.id}\nForwarded to: ${issue.dept}\n\nTrack: https://nagarik.care/t/${issue.id}`
        );
      } else if (text === '2') {
        const list = CIVIC_CATEGORIES.map((c, i) => `${i + 1}. ${c.label}`).join('\n');
        setSession(phone, { step: 'selecting_category' });
        await sendWhatsApp(phone, `Select category:\n\n${list}`);
      }
      return;
    }

    if (session.step === 'selecting_category') {
      const index = parseInt(text) - 1;
      if (index >= 0 && index < CIVIC_CATEGORIES.length) {
        setSession(phone, { step: 'awaiting_confirmation', confirmedCategory: CIVIC_CATEGORIES[index].id });
        await sendWhatsApp(phone, `Category: *${CIVIC_CATEGORIES[index].label}*\n\nReply *1* to submit ?`);
      }
      return;
    }

    if (type === 'audio' && audioUrl) {
      const transcript = await transcribeAudio(audioUrl);
      const category = getCategoryByKeyword(transcript);
      setSession(phone, { step: 'awaiting_location', aiCategory: category?.id });
      await sendWhatsApp(phone, `I heard: _"${transcript}"_\n\n?? Where is this? Share location or type area.`);
      return;
    }

    await sendWhatsApp(phone,
      `?? Welcome to *Nagarik*!\n\nTo report an issue:\n1?? Send a *photo*\n2?? Share your *location*\n3?? Done!\n\n_Civic Visibility. Smarter Cities._`
    );
  } catch (err) {
    console.error('[WhatsApp Bot]', err);
  }
});

export const sendStatusUpdate = async (issue, newStatus) => {
  if (!issue.reporter_phone) return;
  const msgs = {
    in_progress: `?? Update #NGK-${issue.id}: In Progress — ${issue.dept} has acknowledged.`,
    escalated:   `?? Update #NGK-${issue.id}: Escalated to ${issue.escalation_role} due to delay.`,
    resolved:    `? #NGK-${issue.id} marked RESOLVED.\n\nWas it fixed?\nReply *1* YES ?\nReply *2* NO ?`,
  };
  if (msgs[newStatus]) await sendWhatsApp(issue.reporter_phone, msgs[newStatus]);
};

function parseIncoming(body) {
  if (body.type) return { phone: body.mobile, type: body.type, text: body.message?.text, imageUrl: body.message?.url, audioUrl: body.message?.url, latitude: body.message?.latitude, longitude: body.message?.longitude };
  const msg = body.entry?.[0]?.changes?.[0]?.value?.messages?.[0];
  if (!msg) return {};
  return { phone: msg.from, type: msg.type, text: msg.text?.body, imageUrl: msg.image?.id, audioUrl: msg.audio?.id, latitude: msg.location?.latitude, longitude: msg.location?.longitude };
}

export default router;
