function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function formatHour(hour) {
  const period = hour >= 12 ? "PM" : "AM";
  const adjusted = hour % 12 === 0 ? 12 : hour % 12;
  return `${adjusted} ${period}`;
}

function formatDuration(minutes) {
  if (minutes == null || typeof minutes === "undefined") return "—";
  const v = Number(minutes);
  if (Number.isNaN(v)) return "—";
  const totalMinutes = Math.round(v);
  const hours = Math.floor(totalMinutes / 60);
  const mins = totalMinutes % 60;
  if (hours === 0) return `${mins}m`;
  if (mins === 0) return `${hours}h`;
  return `${hours}h ${mins}m`;
}

const ANALYTICS_TZ_OPTIONS = [
  { value: "America/New_York", label: "America/New_York (ET)" },
  { value: "America/Chicago", label: "America/Chicago (CT)" },
  { value: "America/Denver", label: "America/Denver (MT)" },
  { value: "America/Los_Angeles", label: "America/Los_Angeles (PT)" },
  { value: "UTC", label: "UTC" },
];

const ANALYTICS_TZ_FRIENDLY = {
  "America/New_York": "Eastern Time (ET)",
  "America/Chicago": "Central Time (CT)",
  "America/Denver": "Mountain Time (MT)",
  "America/Los_Angeles": "Pacific Time (PT)",
  UTC: "UTC",
};

function normalizeAnalyticsTimezone(applied) {
  const v = (applied || "").trim();
  if (v && ANALYTICS_TZ_OPTIONS.some((o) => o.value === v)) return v;
  return "America/New_York";
}

function friendlyTimezoneLabel(iana) {
  return ANALYTICS_TZ_FRIENDLY[iana] || iana;
}

function allTimesShownLine(iana) {
  return `All times shown in ${friendlyTimezoneLabel(iana)}`;
}

/** Sunday = 0 … Saturday = 6; hour 0–23 in `timeZone`. */
function dowHourInTimezone(unixSec, timeZone) {
  const d = new Date(unixSec * 1000);
  const wdFmt = new Intl.DateTimeFormat("en-US", { timeZone, weekday: "short" });
  const hourFmt = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour: "numeric",
    hour12: false,
  });
  const wd = wdFmt.format(d);
  let hour = 0;
  for (const p of hourFmt.formatToParts(d)) {
    if (p.type === "hour") {
      hour = parseInt(p.value, 10);
      break;
    }
  }
  if (Number.isNaN(hour) || hour === 24) hour = 0;
  const map = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  const key = wd.slice(0, 3);
  const dow = map[key] ?? 0;
  return { dow, hour };
}

function inBusinessWindowEt(unixSec) {
  const d = new Date(unixSec * 1000);
  const wdFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
  });
  const hourFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    hour12: false,
  });
  const wd = wdFmt.format(d).slice(0, 3);
  const map = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5 };
  let hour = 0;
  for (const p of hourFmt.formatToParts(d)) {
    if (p.type === "hour") {
      hour = parseInt(p.value, 10);
      break;
    }
  }
  const isWeekday = map[wd] != null;
  const isBusinessHour = hour >= 8 && hour < 18;
  return isWeekday && isBusinessHour;
}

function buildHeatmapFromTimestamps(timestamps, timeZone) {
  if (!timestamps || !timestamps.length) return null;
  const grid = Array.from({ length: 7 }, () => Array(24).fill(0));
  for (const raw of timestamps) {
    const sec = Number(raw);
    if (Number.isNaN(sec)) continue;
    const { dow, hour } = dowHourInTimezone(sec, timeZone);
    if (dow >= 0 && dow < 7 && hour >= 0 && hour < 24) grid[dow][hour] += 1;
  }
  return grid;
}

let __analyticsBundle = null;
let __insightsBundle = null;

function getAnalyticsScannedChannels(bundle) {
  const raw = bundle?.analyticsScannedChannels ?? bundle?.analytics_scanned_channels;
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const row of raw) {
    if (!row || typeof row !== "object") continue;
    const channelId = String(row.channelId ?? row.channel_id ?? "").trim();
    if (!channelId) continue;
    const nm = String(row.channelName ?? row.channel_name ?? "").trim();
    out.push({ channelId, channelName: nm || channelId });
  }
  return out;
}

/** One row from API (camelCase or snake_case). Returns null if unusable. */
function normalizeAnalyticsApiMessage(m) {
  if (!m || typeof m !== "object") return null;
  const tsRaw = m.timestamp ?? m.ts;
  if (tsRaw == null) return null;
  const tsf = Number(tsRaw);
  if (Number.isNaN(tsf)) return null;
  let channelId = String(m.channelId ?? m.channel_id ?? m.channel ?? "").trim();
  if (!channelId) {
    const chObj = m.channel;
    if (chObj && typeof chObj === "object") {
      channelId = String(chObj.id ?? chObj.channel_id ?? "").trim();
    }
  }
  if (!channelId) {
    const mid = m.messageId ?? m.message_id;
    const s = typeof mid === "string" ? mid : "";
    const colon = s.indexOf(":");
    if (colon > 0) channelId = s.slice(0, colon).trim();
  }
  if (!channelId) return null;
  const nm = String(m.channelName ?? m.channel_name ?? "").trim();
  const channelName = nm || channelId;
  const threadId = m.threadId ?? m.thread_id ?? null;
  const userId = String(m.userId ?? m.user_id ?? "").trim();
  const roleRaw = String(m.role ?? "external").toLowerCase();
  const role = roleRaw === "staff" ? "staff" : "external";
  return { channelId, channelName, threadId, userId, timestamp: tsf, role };
}

function getRawAnalyticsMessagesArray(data) {
  let raw = data?.analyticsMessages ?? data?.analytics_messages;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      raw = null;
    }
  }
  return Array.isArray(raw) ? raw : [];
}

function getAnalyticsMessages(data) {
  const raw = getRawAnalyticsMessagesArray(data);
  const out = [];
  for (const row of raw) {
    const n = normalizeAnalyticsApiMessage(row);
    if (n) out.push(n);
  }
  return out;
}

function round4(n) {
  return Math.round(Number(n) * 10000) / 10000;
}

function medianMinutes(vals) {
  if (!vals.length) return 0;
  const s = [...vals].sort((a, b) => a - b);
  const n = s.length;
  const mid = Math.floor(n / 2);
  if (n % 2 === 1) return s[mid];
  return (s[mid - 1] + s[mid]) / 2;
}

function p90Minutes(vals) {
  if (!vals.length) return 0;
  const s = [...vals].sort((a, b) => a - b);
  const n = s.length;
  if (n === 1) return s[0];
  const idx = Math.floor(0.9 * (n - 1));
  return s[idx];
}

function toIsoDayFromUnixSec(unixSec) {
  const sec = Number(unixSec);
  if (Number.isNaN(sec)) return "";
  const d = new Date(sec * 1000);
  if (Number.isNaN(d.getTime())) return "";
  return d.toISOString().slice(0, 10);
}

function getApiTrafficActivityRows(data) {
  let raw =
    data?.apiTrafficActivity ??
    data?.api_traffic_activity ??
    data?.apiActivity ??
    data?.api_activity ??
    null;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw);
    } catch {
      raw = null;
    }
  }
  const out = [];
  if (Array.isArray(raw)) {
    for (const row of raw) {
      if (!row || typeof row !== "object") continue;
      const channelId = String(row.channel_id ?? row.channelId ?? "").trim();
      const tsRaw = row.timestamp;
      const tsf = Number(tsRaw);
      if (!channelId || Number.isNaN(tsf)) continue;
      const endpoint = String(row.endpoint ?? "").trim();
      out.push({ channel_id: channelId, timestamp: tsf, endpoint });
    }
    return out;
  }

  // Fallback for MVP: if dedicated API traffic rows are not provided,
  // reuse analytics messages as generic call events so the trend still renders.
  const msgs = getAnalyticsMessages(data);
  for (const m of msgs) {
    const channelId = String(m.channelId || "").trim();
    const tsf = Number(m.timestamp);
    if (!channelId || Number.isNaN(tsf)) continue;
    out.push({ channel_id: channelId, timestamp: tsf, endpoint: "" });
  }
  return out;
}

function buildDailyCallCountMap(rows) {
  const byDay = {};
  for (const row of rows || []) {
    const isoDay = toIsoDayFromUnixSec(row.timestamp);
    if (!isoDay) continue;
    byDay[isoDay] = (byDay[isoDay] || 0) + 1;
  }
  return byDay;
}

function buildDailyTrafficSeries(dayMap) {
  return Object.keys(dayMap || {})
    .sort((a, b) => a.localeCompare(b))
    .map((date) => ({ date, call_count: Number(dayMap[date] || 0) }));
}

function computeTrafficInsight(series) {
  if (!Array.isArray(series) || !series.length) {
    return { avg_daily_calls: 0, latest_day_calls: 0, insight: "Stable Activity" };
  }
  const total = series.reduce((sum, pt) => sum + Number(pt.call_count || 0), 0);
  const avg = total / series.length;
  const latest = Number(series[series.length - 1].call_count || 0);
  let insight = "Stable Activity";
  if (latest > avg * 2) insight = "Traffic Spike";
  else if (latest < avg * 0.3) insight = "Traffic Drop-off";
  return {
    avg_daily_calls: Math.round(avg * 100) / 100,
    latest_day_calls: latest,
    insight,
  };
}

function trafficInsightSummary(status) {
  if (status === "Traffic Spike") {
    return "API traffic is significantly above normal levels, which may indicate active testing or launch preparation.";
  }
  if (status === "Traffic Drop-off") {
    return "API activity has decreased noticeably compared to baseline, which may indicate stalled integration activity.";
  }
  return "API activity has remained relatively steady over the selected time period.";
}

function averageFromNumbers(vals) {
  if (!vals.length) return 0;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function computeTopEndpoints(rows, limit = 5) {
  const byEndpoint = new Map();
  for (const row of rows || []) {
    const endpoint = String(row.endpoint || "").trim();
    if (!endpoint) continue;
    byEndpoint.set(endpoint, (byEndpoint.get(endpoint) || 0) + 1);
  }
  return [...byEndpoint.entries()]
    .map(([endpoint, count]) => ({ endpoint, count }))
    .sort((a, b) => b.count - a.count || a.endpoint.localeCompare(b.endpoint))
    .slice(0, limit);
}

function renderTrafficLineChart(series) {
  if (!Array.isArray(series) || !series.length) {
    return `<p class="analytics-kpi-subtitle">No API traffic events available for this channel.</p>`;
  }
  const width = 720;
  const height = 220;
  const pad = 32;
  const maxY = Math.max(1, ...series.map((d) => Number(d.call_count || 0)));
  const n = series.length;
  const stepX = n > 1 ? (width - pad * 2) / (n - 1) : 0;
  const points = series
    .map((d, i) => {
      const x = pad + i * stepX;
      const y = height - pad - (Number(d.call_count || 0) / maxY) * (height - pad * 2);
      return { x, y, date: d.date, v: Number(d.call_count || 0) };
    })
    .map((p) => `${p.x},${p.y}`);

  const xFirst = series[0].date;
  const xLast = series[series.length - 1].date;
  return `
    <div class="heatmap-wrap" style="padding:0.75rem;">
      <svg viewBox="0 0 ${width} ${height}" width="100%" height="220" role="img" aria-label="API calls per day line chart">
        <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="#cbd5e1" stroke-width="1" />
        <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" stroke="#cbd5e1" stroke-width="1" />
        <polyline fill="none" stroke="#0891b2" stroke-width="3" points="${points.join(" ")}"></polyline>
      </svg>
      <div style="display:flex;justify-content:space-between;font-size:0.75rem;color:#64748b;margin-top:0.25rem;">
        <span>${escapeHtml(xFirst)}</span>
        <span>Max: ${maxY} calls/day</span>
        <span>${escapeHtml(xLast)}</span>
      </div>
    </div>`;
}

/**
 * Mirrors server analytics_compute on filtered messages (roles precomputed).
 */
function computeAnalyticsFromMsgs(analyticsMsgs, timeZone) {
  const rowsIn = (analyticsMsgs || []).map((m) => ({
    channel_id: m.channelId,
    channel_name: m.channelName,
    thread_id: m.threadId,
    user_id: m.userId,
    timestamp: m.timestamp,
    role: m.role,
  }));

  const totalMessages = rowsIn.length;

  const heatmap = Array.from({ length: 7 }, () => Array(24).fill(0));
  const heatmapTimestamps = [];
  for (const m of rowsIn) {
    const ts = m.timestamp;
    if (ts == null || Number.isNaN(Number(ts))) continue;
    const sec = Number(ts);
    const { dow, hour } = dowHourInTimezone(sec, timeZone);
    if (dow >= 0 && dow < 7 && hour >= 0 && hour < 24) {
      heatmap[dow][hour] += 1;
      heatmapTimestamps.push(sec);
    }
  }

  const byThread = new Map();
  for (const m of rowsIn) {
    const tid = m.thread_id;
    if (tid == null) continue;
    const k = String(tid);
    if (!byThread.has(k)) byThread.set(k, []);
    byThread.get(k).push(m);
  }

  const response_times_min = [];
  for (const arr of byThread.values()) {
    arr.sort((a, b) => Number(a.timestamp) - Number(b.timestamp));
    const rows = arr.filter((r) => inBusinessWindowEt(Number(r.timestamp) || 0));
    if (!rows.length) continue;
    let first_ext_i = null;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].role === "external") {
        first_ext_i = i;
        break;
      }
    }
    if (first_ext_i === null) continue;
    const ext_ts = Number(rows[first_ext_i].timestamp) || 0;
    let staff_ts = null;
    for (let j = first_ext_i + 1; j < rows.length; j++) {
      if (rows[j].role === "staff") {
        staff_ts = Number(rows[j].timestamp) || 0;
        break;
      }
    }
    if (staff_ts === null) continue;
    const delta_sec = staff_ts - ext_ts;
    if (delta_sec >= 0) response_times_min.push(delta_sec / 60);
  }

  const follow_up_response_times_min = [];
  for (const arr of byThread.values()) {
    arr.sort((a, b) => Number(a.timestamp) - Number(b.timestamp));
    const rows = arr.filter((r) => inBusinessWindowEt(Number(r.timestamp) || 0));
    if (!rows.length) continue;
    let first_ext_i = null;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i].role === "external") {
        first_ext_i = i;
        break;
      }
    }
    let first_staff_j = null;
    if (first_ext_i !== null) {
      for (let j = first_ext_i + 1; j < rows.length; j++) {
        if (rows[j].role === "staff") {
          first_staff_j = j;
          break;
        }
      }
    }
    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      if (row.role !== "external") continue;
      let staff_j = null;
      for (let j = i + 1; j < rows.length; j++) {
        if (rows[j].role === "staff") {
          staff_j = j;
          break;
        }
      }
      if (staff_j === null) continue;
      if (
        first_ext_i !== null &&
        first_staff_j !== null &&
        i === first_ext_i &&
        staff_j === first_staff_j
      ) {
        continue;
      }
      const ext_ts = Number(row.timestamp) || 0;
      const st_ts = Number(rows[staff_j].timestamp) || 0;
      const delta_sec = st_ts - ext_ts;
      if (delta_sec >= 0) follow_up_response_times_min.push(delta_sec / 60);
    }
  }

  let avg = 0;
  let med = 0;
  let p90 = 0;
  if (response_times_min.length) {
    avg = response_times_min.reduce((a, b) => a + b, 0) / response_times_min.length;
    med = medianMinutes(response_times_min);
    p90 = p90Minutes(response_times_min);
  }

  let avg_fu = 0;
  let med_fu = 0;
  if (follow_up_response_times_min.length) {
    avg_fu =
      follow_up_response_times_min.reduce((a, b) => a + b, 0) /
      follow_up_response_times_min.length;
    med_fu = medianMinutes(follow_up_response_times_min);
  }

  return {
    avgResponseTime: round4(avg),
    medianResponseTime: round4(med),
    p90ResponseTime: round4(p90),
    avgFollowUpResponseTime: round4(avg_fu),
    medianFollowUpResponseTime: round4(med_fu),
    totalMessages,
    heatmap,
    heatmapTimestamps,
  };
}

function displayChannelLabel(label) {
  if (typeof OrcaChannelMask !== "undefined" && OrcaChannelMask.maskChannelDisplayName) {
    return OrcaChannelMask.maskChannelDisplayName(label);
  }
  return label;
}

function fillChannelSelect(selectEl, bundle) {
  if (!selectEl) return;
  const msgs = getAnalyticsMessages(bundle);
  const seen = new Map();
  for (const m of msgs) {
    if (!m.channelId) continue;
    const label = m.channelName || m.channelId;
    if (!seen.has(m.channelId)) seen.set(m.channelId, label);
  }
  for (const s of getAnalyticsScannedChannels(bundle)) {
    if (!s.channelId) continue;
    if (!seen.has(s.channelId)) seen.set(s.channelId, s.channelName || s.channelId);
  }
  const pairs = [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  selectEl.innerHTML =
    `<option value="ALL">All Channels</option>` +
    pairs
      .map(
        ([id, label]) =>
          `<option value="${escapeHtml(id)}">${escapeHtml(displayChannelLabel(label))}</option>`
      )
      .join("");
  selectEl.value = "ALL";
}

function renderPeakTimesChartsHtml(grid) {
  const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  let max = 0;
  for (let d = 0; d < 7; d++) {
    const row = grid[d] || [];
    for (let h = 0; h < 24; h++) max = Math.max(max, row[h] || 0);
  }

  const hourCounts = Array(24).fill(0);
  for (let h = 0; h < 24; h++) {
    for (let d = 0; d < 7; d++) {
      hourCounts[h] += (grid[d] || [])[h] || 0;
    }
  }
  let peakHour = 0;
  let peakCount = hourCounts[0];
  for (let h = 1; h < 24; h++) {
    if (hourCounts[h] > peakCount) {
      peakCount = hourCounts[h];
      peakHour = h;
    }
  }
  const barMax = hourCounts.reduce((a, b) => Math.max(a, b), 0) || 1;
  let barsHtml = '<div class="hour-bars-row" role="img" aria-label="Total messages per hour of day">';
  for (let h = 0; h < 24; h++) {
    const cnt = hourCounts[h];
    const pct = barMax > 0 ? (cnt / barMax) * 100 : 0;
    const label = escapeHtml(formatHour(h));
    barsHtml += `<div class="hour-bar-col" title="${cnt} messages"><div class="hour-bar-fill-wrap"><div class="hour-bar-fill" style="height:${pct}%"></div></div><div class="hour-bar-x">${label}</div></div>`;
  }
  barsHtml += "</div>";

  const peakLine =
    peakCount > 0
      ? `<p class="hour-peak-line">Peak activity: ${escapeHtml(formatHour(peakHour))} (${peakCount} messages)</p>`
      : `<p class="hour-peak-line">Peak activity: no messages in this sample by hour.</p>`;

  let header = '<tr><th class="corner"></th>';
  for (let h = 0; h < 24; h++) {
    header += `<th class="hour" scope="col">${escapeHtml(formatHour(h))}</th>`;
  }
  header += "</tr>";

  let body = "";
  for (let d = 0; d < 7; d++) {
    body += `<tr><th class="day" scope="row">${days[d]}</th>`;
    const row = grid[d] || [];
    for (let h = 0; h < 24; h++) {
      const c = row[h] || 0;
      const t = max > 0 ? c / max : 0;
      const bg = `rgba(8, 145, 178, ${0.08 + t * 0.82})`;
      const hourLabel = escapeHtml(formatHour(h));
      body += `<td class="cell" style="background:${bg}" title="${days[d]} ${hourLabel} — ${c}">${c}</td>`;
    }
    body += "</tr>";
  }

  return `
      <h3 class="analytics-subheading">Messages per hour (all days)</h3>
      ${peakLine}
      <div class="hour-bar-chart">${barsHtml}</div>
      <h3 class="analytics-subheading">By day and hour</h3>
      <div class="heatmap-wrap">
        <table class="heatmap" aria-label="Messages by day and hour">
          <thead>${header}</thead>
          <tbody>${body}</tbody>
        </table>
      </div>`;
}

function buildDataNotice(data) {
  const n = data.totalMessages ?? 0;
  const ch = data.channelsScanned ?? 0;
  const cfs = data.channelsFromSlack ?? 0;
  const fe = data.slackChannelFilterEntries ?? 0;
  const parts = [];
  if (n === 0) {
    if (ch === 0) {
      if (fe > 0 && cfs > 0) {
        parts.push(
          `SLACK_CHANNEL_IDS has ${fe} entr${fe === 1 ? "y" : "ies"}, but none matched the ${cfs} channel(s) Slack returned. Fix typos, use this workspace’s C… IDs, or paste <#C…|name> / archive links. The bot must also be a member of each channel.`
        );
      } else if (fe > 0 && cfs === 0) {
        parts.push(
          "SLACK_CHANNEL_IDS is set, but Slack returned 0 channels. Check the bot token scopes (e.g. channels:read) and that the app is installed in this workspace."
        );
      } else if (fe === 0 && cfs === 0) {
        parts.push(
          "Slack returned 0 channels. Invite the bot to at least one public or private channel, or set SLACK_CHANNEL_IDS to channels it belongs to, then restart."
        );
      } else {
        parts.push(
          "No channels in the scan list. If SLACK_CHANNEL_IDS is set, each value must resolve to a channel ID the bot can see; otherwise the app uses every channel the bot is in."
        );
      }
    } else {
      parts.push(
        `Scanned ${ch} channel(s) but loaded 0 messages. Those channels may have no history, or the bot may be missing history scopes / membership.`
      );
    }
  } else {
    parts.push(`Loaded ${n} message(s) from ${ch} channel(s).`);
    const days = data.historyDaysConfig;
    const tex = data.threadsExpanded;
    const cap = data.threadsExpandedCap;
    const pages = data.historyPages ?? 1;
    if (days != null && tex != null && cap != null) {
      parts.push(
        `Quick Slack sample: ~last ${days} day(s), ${pages} history page per channel, ${tex} thread expansions (global cap ${cap}, per-channel cap ${data.threadsPerChannelCap ?? "—"}).`
      );
    }
    const omit = data.channelsOmitted ?? 0;
    if (omit > 0) {
      parts.push(
        `${omit} channel(s) not scanned (ANALYTICS_MAX_CHANNELS). Raise it for more coverage (slower).`
      );
    }
    if (data.threadsCapped) {
      parts.push("Hit the global thread-expansion cap; metrics are partial.");
    }
    const xex = data.channelsExcludedFromAnalytics ?? data.channels_excluded_from_analytics ?? 0;
    if (xex > 0) {
      parts.push(
        `${xex} channel(s) omitted from analytics (exclude list; see ANALYTICS_EXCLUDE_CHANNEL_NAMES / IDS in .env).`
      );
    }
    if (!data.staffIdsConfigured) {
      parts.push(
        "SLACK_STAFF_USER_IDS is empty, so every user is treated as external and first-response times cannot appear. Add internal Slack user IDs (comma-separated) in .env and restart."
      );
    } else if (
      data.staffIdsConfigured &&
      (data.avgResponseTime === 0 || data.avgResponseTime === 0.0) &&
      (data.medianResponseTime === 0 || data.medianResponseTime === 0.0) &&
      (data.p90ResponseTime === 0 || data.p90ResponseTime === 0.0)
    ) {
      parts.push(
        "No threads matched first external then staff reply (or staff never replied after the first external message). Only threaded messages count."
      );
    }
  }
  if (!parts.length) return "";
  return `<p class="analytics-data-notice" role="status">${escapeHtml(parts.join(" "))}</p>`;
}

function buildCopilotBlock(data, insightsData) {
  const avgFirst = Number(data?.avgResponseTime ?? 0);
  const avgFollow = Number(data?.avgFollowUpResponseTime ?? 0);
  const responseDelayInsight = avgFollow > avgFirst;

  const responseText = responseDelayInsight
    ? `Threads may show integration friction: follow-up response times are slower than initial responses (${formatDuration(avgFollow)} vs ${formatDuration(avgFirst)}).`
    : `Support flow in this sample looks steady (${formatDuration(avgFollow)} follow-up vs ${formatDuration(avgFirst)} initial).`;

  const topError = Array.isArray(insightsData?.topErrors) ? insightsData.topErrors[0] : null;
  const topQuestion = Array.isArray(insightsData?.topQuestions) ? insightsData.topQuestions[0] : null;
  const errorCount = Number(topError?.count ?? 0);
  const questionCount = Number(topQuestion?.count ?? 0);

  let topIssueText = "Top issue: no repeated questions or error tokens found in this sample.";
  let issueType = "none";

  if (errorCount > 0 || questionCount > 0) {
    if (errorCount >= questionCount && topError) {
      issueType = "error";
      topIssueText = `Top issue: ${topError.token || "unknown error"} appeared ${errorCount} times`;
    } else if (topQuestion) {
      issueType = "question";
      topIssueText = `Top issue: ${topQuestion.topic || "unknown question"} appeared ${questionCount} times`;
    }
  }

  return `
    <div class="analytics-block copilot-card" id="analyticsCopilotBlock">
      <h2 class="copilot-title">ORCA Copilot</h2>
      <div class="copilot-row">
        <h3>🚨 ORCA Insight</h3>
        <p>${escapeHtml(responseText)}</p>
      </div>
      <div class="copilot-row">
        <h3>🔎 Top Issue</h3>
        <p>${escapeHtml(topIssueText)}</p>
      </div>
    </div>`;
}

function renderAnalytics(data, insightsData = null) {
  const el = document.getElementById("analyticsContent");
  if (!el) return;

  __analyticsBundle = data;

  const copilot = buildCopilotBlock(data, insightsData);
  const notice = buildDataNotice(data);
  const canFilter = getAnalyticsMessages(data).length > 0;

  const defaultTz = normalizeAnalyticsTimezone(data.analyticsTimezoneApplied);
  const optionsHtml = ANALYTICS_TZ_OPTIONS.map(
    (o) =>
      `<option value="${escapeHtml(o.value)}"${o.value === defaultTz ? " selected" : ""}>${escapeHtml(
        o.label
      )}</option>`
  ).join("");

  const filtersBlock = `
    <div class="analytics-block" id="analyticsFiltersBlock">
      <div class="analytics-filter-grid">
        <div class="analytics-tz-row">
          <label for="analyticsChannelSelect">Channel</label>
          <select id="analyticsChannelSelect" class="analytics-tz-select"${
            canFilter ? "" : " disabled"
          }><option value="ALL">All Channels</option></select>
        </div>
        <div class="analytics-tz-row">
          <label for="analyticsTzSelect">Timezone</label>
          <select id="analyticsTzSelect" class="analytics-tz-select">${optionsHtml}</select>
        </div>
      </div>
      <p class="analytics-scope-line" id="analyticsScopeLine"></p>
    </div>`;

  const kpis = `
    <div class="analytics-block">
      <h2>Response Time Metrics</h2>
      <p class="analytics-kpi-subtitle">Based on first staff reply to external message</p>
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">Avg response</div>
          <div class="kpi-value" id="analyticsKpiAvg">${escapeHtml(formatDuration(data.avgResponseTime))}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Median</div>
          <div class="kpi-value" id="analyticsKpiMedian">${escapeHtml(
            formatDuration(data.medianResponseTime)
          )}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">P90</div>
          <div class="kpi-value" id="analyticsKpiP90">${escapeHtml(formatDuration(data.p90ResponseTime))}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Total messages</div>
          <div class="kpi-value" id="analyticsKpiTotal">${data.totalMessages ?? 0}</div>
        </div>
      </div>
      <h3 class="analytics-section-title">Follow-up Response Time</h3>
      <p class="analytics-kpi-subtitle analytics-kpi-subtitle--tight">
        Each external message to the next staff reply; excludes the first-response pair per thread.
      </p>
      <div class="kpi-grid kpi-grid--followup">
        <div class="kpi-card">
          <div class="kpi-label">Avg follow-up</div>
          <div class="kpi-value" id="analyticsKpiFuAvg">${escapeHtml(
            formatDuration(data.avgFollowUpResponseTime)
          )}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Median follow-up</div>
          <div class="kpi-value" id="analyticsKpiFuMedian">${escapeHtml(
            formatDuration(data.medianFollowUpResponseTime)
          )}</div>
        </div>
      </div>
    </div>`;

  const chartsShell = `
    <div class="analytics-block" id="analyticsChartsBlock">
      <h2>Peak message times</h2>
      <p class="analytics-tz-shown" id="analyticsTzShown">${escapeHtml(allTimesShownLine(defaultTz))}</p>
      <div id="analyticsChartsInner"></div>
    </div>`;

  const trafficShell = `
    <div class="analytics-block" id="apiTrafficPatternsBlock">
      <h2>API Traffic Patterns</h2>
      <h3 class="analytics-subheading">Traffic Chart</h3>
      <div id="apiTrafficChart"></div>

      <h3 class="analytics-subheading" style="margin-top:1rem;">Traffic Status</h3>
      <div class="kpi-grid kpi-grid--followup">
        <div class="kpi-card">
          <div class="kpi-label">Avg Daily Calls</div>
          <div class="kpi-value" id="apiTrafficAvgDaily">0</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Latest Daily Calls</div>
          <div class="kpi-value" id="apiTrafficLatestDaily">0</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Traffic Status</div>
          <div class="kpi-value" id="apiTrafficStatus">Stable Activity</div>
        </div>
      </div>
      <p class="analytics-kpi-subtitle" id="apiTrafficInsightText">
        API activity has remained relatively steady over the selected time period.
      </p>

      <h3 class="analytics-subheading" style="margin-top:1rem;">Top Endpoints</h3>
      <div id="apiTrafficTopEndpoints"></div>
    </div>`;

  el.innerHTML = copilot + notice + filtersBlock + kpis + chartsShell + trafficShell;

  const channelSel = el.querySelector("#analyticsChannelSelect");
  const tzSel = el.querySelector("#analyticsTzSelect");
  const scopeLine = el.querySelector("#analyticsScopeLine");
  const inner = el.querySelector("#analyticsChartsInner");
  const shown = el.querySelector("#analyticsTzShown");
  const trafficChart = el.querySelector("#apiTrafficChart");
  const trafficAvg = el.querySelector("#apiTrafficAvgDaily");
  const trafficLatest = el.querySelector("#apiTrafficLatestDaily");
  const trafficStatus = el.querySelector("#apiTrafficStatus");
  const trafficInsightText = el.querySelector("#apiTrafficInsightText");
  const trafficTopEndpoints = el.querySelector("#apiTrafficTopEndpoints");

  if (channelSel) fillChannelSelect(channelSel, data);

  function scopeDisplayName() {
    if (!canFilter || !channelSel || !channelSel.value || channelSel.value === "ALL") {
      return "All Channels";
    }
    const opt = channelSel.options[channelSel.selectedIndex];
    return opt ? opt.textContent.trim() : "All Channels";
  }

  function setKpisFromComputed(comp) {
    const avgEl = el.querySelector("#analyticsKpiAvg");
    const medEl = el.querySelector("#analyticsKpiMedian");
    const p90El = el.querySelector("#analyticsKpiP90");
    const totEl = el.querySelector("#analyticsKpiTotal");
    const fuAvgEl = el.querySelector("#analyticsKpiFuAvg");
    const fuMedEl = el.querySelector("#analyticsKpiFuMedian");
    if (avgEl) avgEl.textContent = formatDuration(comp.avgResponseTime);
    if (medEl) medEl.textContent = formatDuration(comp.medianResponseTime);
    if (p90El) p90El.textContent = formatDuration(comp.p90ResponseTime);
    if (totEl) totEl.textContent = String(comp.totalMessages ?? 0);
    if (fuAvgEl) fuAvgEl.textContent = formatDuration(comp.avgFollowUpResponseTime);
    if (fuMedEl) fuMedEl.textContent = formatDuration(comp.medianFollowUpResponseTime);
  }

  function setKpisFromServer(d) {
    setKpisFromComputed({
      avgResponseTime: d.avgResponseTime,
      medianResponseTime: d.medianResponseTime,
      p90ResponseTime: d.p90ResponseTime,
      totalMessages: d.totalMessages,
      avgFollowUpResponseTime: d.avgFollowUpResponseTime,
      medianFollowUpResponseTime: d.medianFollowUpResponseTime,
    });
  }

  function paintCharts(compOrData, tz) {
    const src = compOrData;
    let grid = buildHeatmapFromTimestamps(src.heatmapTimestamps, tz);
    if (!grid) {
      grid = src.heatmap || Array.from({ length: 7 }, () => Array(24).fill(0));
    }
    if (inner) inner.innerHTML = renderPeakTimesChartsHtml(grid);
    if (shown) shown.textContent = allTimesShownLine(tz);
  }

  function applyAnalyticsView() {
    const tz = tzSel ? tzSel.value : defaultTz;
    if (scopeLine) scopeLine.textContent = `Showing data for: ${scopeDisplayName()}`;
    const ch = channelSel && channelSel.value !== "ALL" ? channelSel.value : "ALL";

    const allTrafficRows = getApiTrafficActivityRows(__analyticsBundle);
    const trafficRows =
      ch === "ALL"
        ? allTrafficRows
        : allTrafficRows.filter((r) => String(r.channel_id) === String(ch));
    const dailyMap = buildDailyCallCountMap(trafficRows);
    const series = buildDailyTrafficSeries(dailyMap);
    const insight = computeTrafficInsight(series);
    const topEndpoints = computeTopEndpoints(trafficRows, 5);

    if (trafficChart) trafficChart.innerHTML = renderTrafficLineChart(series);
    if (trafficAvg) trafficAvg.textContent = String(insight.avg_daily_calls);
    if (trafficLatest) trafficLatest.textContent = String(insight.latest_day_calls);
    if (trafficStatus) trafficStatus.textContent = insight.insight;
    if (trafficInsightText) trafficInsightText.textContent = trafficInsightSummary(insight.insight);
    if (trafficTopEndpoints) {
      if (!topEndpoints.length) {
        trafficTopEndpoints.innerHTML =
          '<p class="analytics-kpi-subtitle">No endpoint data available in this sample.</p>';
      } else {
        const rowsHtml = topEndpoints
          .map(
            (row) =>
              `<tr><td class="mono">${escapeHtml(row.endpoint)}</td><td class="num">${row.count}</td></tr>`
          )
          .join("");
        trafficTopEndpoints.innerHTML = `
          <table class="slow-table" aria-label="Top API endpoints">
            <thead><tr><th>Endpoint</th><th>Calls</th></tr></thead>
            <tbody>${rowsHtml}</tbody>
          </table>`;
      }
    }

    if (!canFilter) {
      setKpisFromServer(data);
      paintCharts(data, tz);
      return;
    }

    const allMsgs = getAnalyticsMessages(__analyticsBundle);
    const filtered =
      ch === "ALL" ? allMsgs : allMsgs.filter((m) => String(m.channelId) === String(ch));
    const comp = computeAnalyticsFromMsgs(filtered, tz);
    setKpisFromComputed(comp);
    paintCharts(comp, tz);
  }

  if (tzSel && inner) {
    applyAnalyticsView();
    tzSel.addEventListener("change", applyAnalyticsView);
    if (channelSel && canFilter) channelSel.addEventListener("change", applyAnalyticsView);
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const boot = await OrcaDataProvider.getBootstrapConfig();
    window.__ORCA_DEMO_MODE__ = Boolean(boot.demoMode);
    const badge = document.getElementById("demoEnvironmentBadge");
    if (badge && boot.demoMode) {
      badge.hidden = false;
    }
    if (window.__ORCA_DEMO_MODE__) {
      OrcaDataProvider.getCompanies().catch(() => {});
    }
  } catch {
    window.__ORCA_DEMO_MODE__ = false;
  }

  const tabSearch = document.getElementById("tabSearch");
  const tabBroadcast = document.getElementById("tabBroadcast");
  const tabAnalytics = document.getElementById("tabAnalytics");
  const panelSearch = document.getElementById("panelSearch");
  const panelBroadcast = document.getElementById("panelBroadcast");
  const panelAnalytics = document.getElementById("panelAnalytics");
  const analyticsRefreshBtn = document.getElementById("analyticsRefreshBtn");
  const analyticsStatus = document.getElementById("analyticsStatus");
  const analyticsContent = document.getElementById("analyticsContent");
  const broadcastChannels = document.getElementById("broadcastChannels");
  const broadcastMessage = document.getElementById("broadcastMessage");
  const broadcastAnnouncement = document.getElementById("broadcastAnnouncement");
  const broadcastSendBtn = document.getElementById("broadcastSendBtn");
  const broadcastStatus = document.getElementById("broadcastStatus");
  const broadcastPreflight = document.getElementById("broadcastPreflight");
  const broadcastSummary = document.getElementById("broadcastSummary");
  const broadcastConfirmModal = document.getElementById("broadcastConfirmModal");
  const broadcastConfirmText = document.getElementById("broadcastConfirmText");
  const broadcastConfirmMessage = document.getElementById("broadcastConfirmMessage");
  const broadcastConfirmChannels = document.getElementById("broadcastConfirmChannels");
  const broadcastConfirmBtn = document.getElementById("broadcastConfirmBtn");
  const broadcastCancelBtn = document.getElementById("broadcastCancelBtn");

  const ingestBtn = document.getElementById("ingestBtn");
  const ingestStatus = document.getElementById("ingestStatus");
  const rolesHint = document.getElementById("rolesHint");
  const askBtn = document.getElementById("askBtn");
  const questionInput = document.getElementById("questionInput");
  const answerEl = document.getElementById("answer");
  let broadcastChannelsLoaded = false;
  let broadcastPreflightLoaded = false;
  let broadcastCanSend = true;
  let pendingBroadcastPayload = null;
  let pendingBroadcastChannels = [];

  async function refreshRolesHint() {
    if (!rolesHint) return;
    try {
      const data = await OrcaDataProvider.getRolesStatus();
      if (!data) return;
      if (data.classification_enabled) {
        rolesHint.textContent = `Staff vs client labels: on (${data.staff_user_id_count} Slack user ID(s) in SLACK_STAFF_USER_IDS).`;
      } else {
        rolesHint.textContent =
          "Staff vs client labels: off — set SLACK_STAFF_USER_IDS in .env and restart to tag internal vs external in indexed text.";
      }
    } catch {
      rolesHint.textContent = "";
    }
  }

  refreshRolesHint();

  async function loadAnalytics() {
    if (!analyticsStatus || !analyticsContent) return;
    if (window.location.protocol === "file:") {
      analyticsStatus.textContent =
        "Open this app from the server (e.g. http://127.0.0.1:8000/ui/), not by opening the HTML file directly.";
      return;
    }
    const demo = await OrcaDataProvider.isDemoMode();
    analyticsStatus.textContent = demo
      ? "Loading demo analytics…"
      : "Loading analytics from Slack (all channels by default; may take a few minutes)…";
    analyticsContent.innerHTML = "";
    const controller = new AbortController();
    const timeoutMs = demo ? 60000 : 300000;
    const tid = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const data = await OrcaDataProvider.getAnalytics(controller.signal);
      let insightsData = null;
      try {
        insightsData = await OrcaDataProvider.getInsights(controller.signal);
      } catch {
        insightsData = null;
      }
      renderAnalytics(data, insightsData);
      __analyticsBundle = data;
      __insightsBundle = insightsData;
      analyticsStatus.textContent = demo ? "Loaded (demo data)." : "Loaded.";
    } catch (e) {
      if (e && e.name === "AbortError") {
        analyticsStatus.textContent = demo
          ? "Timed out loading demo analytics. Retry or check server logs."
          : "Timed out after 5 min (Slack slow or rate-limited). Retry, narrow SLACK_CHANNEL_IDS, or set ANALYTICS_MAX_CHANNELS / thread caps in .env.";
      } else {
        analyticsStatus.textContent = `Error: ${e.message || e}`;
      }
    } finally {
      clearTimeout(tid);
    }
  }

  async function loadBroadcastChannels() {
    if (!broadcastChannels || broadcastChannelsLoaded) return;
    broadcastStatus.textContent = "Loading channels...";
    if (broadcastPreflight) {
      broadcastPreflight.classList.remove("status--warn");
    }
    broadcastChannels.innerHTML = "";
    try {
      const data = await OrcaDataProvider.getBroadcastChannels();
      const rows = Array.isArray(data.channels) ? data.channels : [];
      if (!rows.length) {
        broadcastStatus.textContent = "No channels available to this bot.";
        return;
      }
      for (const row of rows) {
        const id = String(row.id || "").trim();
        const label = String(row.name || id).trim();
        if (!id) continue;
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = displayChannelLabel(label);
        broadcastChannels.appendChild(opt);
      }
      broadcastChannelsLoaded = true;
      broadcastStatus.textContent = "Channels loaded.";
      if (broadcastPreflight && data.warning) {
        broadcastPreflight.classList.add("status--warn");
        broadcastPreflight.textContent = data.warning;
      }
    } catch (e) {
      broadcastStatus.textContent = `Error loading channels: ${e.message || e}`;
    }
  }

  async function loadBroadcastPreflight() {
    if (!broadcastPreflight || broadcastPreflightLoaded) return;
    broadcastPreflight.textContent = "Checking Slack write permissions...";
    broadcastPreflight.classList.remove("status--warn");
    try {
      const data = await OrcaDataProvider.getBroadcastPreflight();
      if (!data.ok) {
        broadcastCanSend = true;
        broadcastPreflight.textContent =
          "Could not verify token scopes automatically. You can still try sending.";
      } else if (!data.has_chat_write) {
        broadcastCanSend = false;
        if (broadcastSendBtn) broadcastSendBtn.disabled = true;
        broadcastPreflight.classList.add("status--warn");
        broadcastPreflight.textContent =
          "Missing required Slack scope: chat:write. Add it in your Slack app, reinstall the app, update token, then restart ORCA.";
      } else if (!data.has_chat_write_public) {
        broadcastCanSend = true;
        broadcastPreflight.classList.add("status--warn");
        broadcastPreflight.textContent =
          "Scope check: chat:write is present. chat:write.public is missing, so posting to public channels may require inviting the bot first.";
      } else {
        broadcastCanSend = true;
        broadcastPreflight.textContent = "Scope check passed: token can post messages.";
      }
      if (broadcastCanSend && broadcastSendBtn) {
        broadcastSendBtn.disabled = false;
      }
      broadcastPreflightLoaded = true;
    } catch (e) {
      broadcastCanSend = true;
      broadcastPreflight.textContent = `Could not verify token scopes: ${e.message || e}`;
      if (broadcastSendBtn) broadcastSendBtn.disabled = false;
    }
  }

  function getSelectedBroadcastChannels() {
    if (!broadcastChannels) return [];
    const selected = [];
    for (const opt of Array.from(broadcastChannels.selectedOptions || [])) {
      const channelId = String(opt.value || "").trim();
      if (!channelId) continue;
      selected.push({
        id: channelId,
        label: String(opt.textContent || channelId),
      });
    }
    return selected;
  }

  function closeBroadcastModal() {
    if (!broadcastConfirmModal) return;
    broadcastConfirmModal.classList.remove("modal--open");
  }

  function openBroadcastConfirmModal() {
    if (!broadcastCanSend) {
      broadcastStatus.textContent =
        "Broadcast is blocked until chat:write scope is added and the app token is updated.";
      return;
    }
    const selected = getSelectedBroadcastChannels();
    const rawMessage = String(broadcastMessage?.value || "");
    const message = rawMessage.trim();
    if (broadcastSummary) broadcastSummary.innerHTML = "";
    if (!selected.length) {
      broadcastStatus.textContent = "Please select at least one channel.";
      return;
    }
    if (!message) {
      broadcastStatus.textContent = "Please enter a message.";
      return;
    }

    const finalMessage = broadcastAnnouncement?.checked ? `📢 ${message}` : message;
    pendingBroadcastPayload = {
      channel_ids: selected.map((s) => s.id),
      message,
      as_announcement: Boolean(broadcastAnnouncement?.checked),
    };
    pendingBroadcastChannels = selected;

    if (broadcastConfirmText) {
      const n = selected.length;
      broadcastConfirmText.textContent = `Are you sure you want to send this message to ${n} channel${n === 1 ? "" : "s"}?`;
    }
    if (broadcastConfirmMessage) {
      broadcastConfirmMessage.textContent = finalMessage;
    }
    if (broadcastConfirmChannels) {
      broadcastConfirmChannels.innerHTML = selected
        .map((s) => `<li>${escapeHtml(displayChannelLabel(s.label))}</li>`)
        .join("");
    }
    if (broadcastConfirmModal) {
      broadcastConfirmModal.classList.add("modal--open");
    }
  }

  function renderBroadcastSummary(result) {
    if (!broadcastSummary) return;
    const sent = Number(result.success_count || 0);
    const failed = Number(result.failure_count || 0);
    let html = `<strong>Sent to ${sent} channel${sent === 1 ? "" : "s"}, ${failed} failed.</strong>`;
    const failures = Array.isArray(result.results)
      ? result.results.filter((r) => !r.success)
      : [];
    if (failures.length > 0) {
      const items = failures
        .map((r) => {
          const cid = String(r.channel_id || "").trim();
          const mapped = pendingBroadcastChannels.find((row) => row.id === cid);
          const label = mapped ? displayChannelLabel(mapped.label) : cid || "unknown-channel";
          const err = String(r.error || "unknown_error");
          return `<li><code>${escapeHtml(label)}</code>: ${escapeHtml(err)}</li>`;
        })
        .join("");
      html += `<ul>${items}</ul>`;
    }
    broadcastSummary.innerHTML = html;
  }

  async function confirmAndSendBroadcast() {
    if (!pendingBroadcastPayload) return;
    if (!broadcastSendBtn || !broadcastConfirmBtn || !broadcastCancelBtn) return;
    broadcastSendBtn.disabled = true;
    broadcastConfirmBtn.disabled = true;
    broadcastCancelBtn.disabled = true;
    broadcastStatus.textContent = "Sending broadcast...";
    try {
      const data = await OrcaDataProvider.postBroadcastSend(pendingBroadcastPayload);
      renderBroadcastSummary(data);
      broadcastStatus.textContent = data.message ? `Broadcast complete. ${data.message}` : "Broadcast complete.";
      closeBroadcastModal();
    } catch (e) {
      broadcastStatus.textContent = `Broadcast failed: ${e.message || e}`;
    } finally {
      pendingBroadcastPayload = null;
      pendingBroadcastChannels = [];
      broadcastSendBtn.disabled = false;
      broadcastConfirmBtn.disabled = false;
      broadcastCancelBtn.disabled = false;
    }
  }

  /** @param {"search" | "broadcast" | "analytics"} which */
  function activateTab(which) {
    if (!tabSearch || !tabBroadcast || !tabAnalytics || !panelSearch || !panelBroadcast || !panelAnalytics) {
      return;
    }
    [tabSearch, tabBroadcast, tabAnalytics].forEach((t) => {
      t.classList.remove("active");
      t.setAttribute("aria-selected", "false");
    });
    [panelSearch, panelBroadcast, panelAnalytics].forEach((p) => p.classList.remove("panel--active"));

    if (which === "search") {
      tabSearch.classList.add("active");
      tabSearch.setAttribute("aria-selected", "true");
      panelSearch.classList.add("panel--active");
    } else if (which === "broadcast") {
      tabBroadcast.classList.add("active");
      tabBroadcast.setAttribute("aria-selected", "true");
      panelBroadcast.classList.add("panel--active");
      loadBroadcastChannels();
      loadBroadcastPreflight();
    } else if (which === "analytics") {
      tabAnalytics.classList.add("active");
      tabAnalytics.setAttribute("aria-selected", "true");
      panelAnalytics.classList.add("panel--active");
      loadAnalytics();
    }
  }

  tabSearch?.addEventListener("click", () => activateTab("search"));
  tabBroadcast?.addEventListener("click", () => activateTab("broadcast"));
  tabAnalytics?.addEventListener("click", () => activateTab("analytics"));
  analyticsRefreshBtn?.addEventListener("click", () => loadAnalytics());
  broadcastSendBtn?.addEventListener("click", openBroadcastConfirmModal);
  broadcastCancelBtn?.addEventListener("click", () => {
    pendingBroadcastPayload = null;
    pendingBroadcastChannels = [];
    closeBroadcastModal();
  });
  broadcastConfirmBtn?.addEventListener("click", confirmAndSendBroadcast);
  broadcastConfirmModal?.addEventListener("click", (evt) => {
    if (evt.target === broadcastConfirmModal) {
      pendingBroadcastPayload = null;
      pendingBroadcastChannels = [];
      closeBroadcastModal();
    }
  });

  ingestBtn?.addEventListener("click", async () => {
    ingestBtn.disabled = true;
    ingestStatus.textContent = "Ingesting Slack messages...";
    try {
      const data = await OrcaDataProvider.postIngest();
      const s = data.summary || {};
      const seen = s.total_threads_seen ?? s.fetched;
      const ins = s.total_inserted ?? s.inserted;
      const skip = s.total_skipped ?? s.skipped;
      const extra = data.message ? ` ${data.message}` : "";
      ingestStatus.textContent = `Done. Threads seen: ${seen ?? "?"}, Inserted: ${
        ins ?? "?"
      }, Skipped: ${skip ?? "?"}.${extra}`;
      refreshRolesHint();
    } catch (e) {
      ingestStatus.textContent = `Error: ${e.message || e}`;
    } finally {
      ingestBtn.disabled = false;
    }
  });

  askBtn?.addEventListener("click", async () => {
    const question = questionInput.value.trim();
    if (!question) {
      answerEl.textContent = "Please enter a question first.";
      return;
    }

    askBtn.disabled = true;
    answerEl.textContent = "Thinking...";

    try {
      const data = await OrcaDataProvider.postAsk(question);
      answerEl.textContent = data.answer || "(No answer returned.)";
    } catch (e) {
      answerEl.textContent = `Error: ${e.message || e}`;
    } finally {
      askBtn.disabled = false;
    }
  });
});
