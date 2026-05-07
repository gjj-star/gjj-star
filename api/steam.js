const STEAM_ID = process.env.STEAM_ID || '76561199043274708';
const STEAM_API_KEY = process.env.STEAM_API_KEY || '5FC0FE329803936382BC3DAD855A2A68';
const ACHIEVEMENT_CONCURRENCY = 4;
const COMPLETION_SCAN_LIMIT = 30;
const API_TIMEOUT_MS = 8500;

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    res.status(204).end();
    return;
  }

  try {
    res.status(200).json(await getAll());
  } catch (error) {
    res.status(500).json({
      error: error.message,
      cause: error.cause?.message || error.cause?.code || '',
    });
  }
}

async function getAll() {
  const profile = await getProfile();
  const games = await getGamesData();
  const achievements = await withTimeout(
    getCompletedGames(games.games),
    API_TIMEOUT_MS,
    { count: 0, games: [], scanned: 0, partial: true }
  );
  return { profile, games, achievements };
}

async function getProfile() {
  const xml = await fetchXML(`https://steamcommunity.com/profiles/${STEAM_ID}/?xml=1`);
  return parseProfile(xml);
}

function parseProfile(xml) {
  const onlineState = xmlGet(xml, 'onlineState');
  const inGame = xmlGet(xml, 'inGameInfo');
  const gameName = inGame ? xmlGet(inGame, 'gameName') : '';

  let status;
  if (inGame && gameName) status = { code: 1, text: '游戏中', cls: 'playing', game: gameName };
  else if (onlineState === 'online') status = { code: 1, text: '在线', cls: 'online' };
  else status = { code: 0, text: '离线', cls: 'offline' };

  return {
    steamid: STEAM_ID,
    name: xmlGet(xml, 'steamID') || 'Unknown',
    avatar: xmlGet(xml, 'avatarFull') || xmlGet(xml, 'avatarMedium'),
    profileurl: `https://steamcommunity.com/profiles/${STEAM_ID}/`,
    status,
    level: xmlGet(xml, 'steamLevel') || '',
  };
}

async function getGamesData() {
  const data = await steamFetch('/IPlayerService/GetOwnedGames/v1/', {
    include_appinfo: 1,
    include_played_free_games: 1,
  });
  const games = (data.response?.games || [])
    .sort((a, b) => b.playtime_forever - a.playtime_forever)
    .map(game => ({
      appid: game.appid,
      name: game.name,
      icon: game.img_icon_url ? `https://media.steampowered.com/steamcommunity/public/images/apps/${game.appid}/${game.img_icon_url}.jpg` : '',
      hours: Math.round(game.playtime_forever / 60 * 10) / 10,
    }));

  return {
    count: games.length,
    totalHours: Math.round(games.reduce((sum, game) => sum + game.hours, 0)),
    top10: games.slice(0, 10),
    games,
  };
}

async function getCompletedGames(games) {
  const scannedGames = games.filter(game => game.hours > 0).slice(0, COMPLETION_SCAN_LIMIT);
  const results = await mapConcurrent(scannedGames, ACHIEVEMENT_CONCURRENCY, getGameCompletion);
  const completed = results
    .filter(Boolean)
    .sort((a, b) => b.hours - a.hours || a.name.localeCompare(b.name, 'zh-CN'));

  return { count: completed.length, games: completed, scanned: scannedGames.length };
}

async function getGameCompletion(game) {
  try {
    const data = await steamFetch('/ISteamUserStats/GetPlayerAchievements/v0001/', { appid: game.appid });
    const achievements = data.playerstats?.achievements || [];
    if (achievements.length === 0) return null;

    const unlocked = achievements.filter(achievement => Number(achievement.achieved) === 1).length;
    if (unlocked !== achievements.length) return null;

    return {
      appid: game.appid,
      name: game.name,
      icon: game.icon,
      hours: game.hours,
      unlocked,
      total: achievements.length,
    };
  } catch {
    return null;
  }
}

async function steamFetch(path, params = {}) {
  const url = new URL(`https://api.steampowered.com${path}`);
  url.searchParams.set('key', STEAM_API_KEY);
  url.searchParams.set('steamid', STEAM_ID);
  url.searchParams.set('format', 'json');
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));

  const response = await fetch(url, { signal: AbortSignal.timeout(API_TIMEOUT_MS) });
  if (!response.ok) throw new Error(`Steam API ${path}: ${response.status}`);
  return response.json();
}

async function fetchXML(url) {
  const response = await fetch(url, {
    signal: AbortSignal.timeout(API_TIMEOUT_MS),
    headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120' },
  });
  if (!response.ok) throw new Error(`Fetch ${url}: ${response.status}`);
  return response.text();
}

async function mapConcurrent(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const index = next++;
      results[index] = await fn(items[index], index);
    }
  });
  await Promise.all(workers);
  return results;
}

async function withTimeout(promise, ms, fallback) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise(resolve => {
        timer = setTimeout(() => resolve(fallback), ms);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

function xmlGet(xml, tag) {
  const cdata = xml.match(new RegExp(`<${tag}><!\\[CDATA\\[([\\s\\S]*?)\\]\\]></${tag}>`));
  if (cdata) return cdata[1].trim();
  const match = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`));
  return match ? match[1].trim() : '';
}
