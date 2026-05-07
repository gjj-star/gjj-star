import http from 'node:http';

const STEAM_ID = process.env.STEAM_ID || '76561199043274708';
const STEAM_API_KEY = process.env.STEAM_API_KEY || '';
const PORT = Number(process.env.PORT || 8787);
const ACHIEVEMENT_CONCURRENCY = 6;
const COMPLETION_SCAN_LIMIT = 120;
const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Content-Type': 'application/json; charset=utf-8',
};

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') return send(res, null, 204);

  const url = new URL(req.url, `http://${req.headers.host}`);
  try {
    if (url.pathname === '/' || url.pathname === '/all') return send(res, await getAll());
    if (url.pathname === '/games') return send(res, await getGamesData());
    if (url.pathname === '/achievements') return send(res, await getCompletedGamesFromOwnedGames());
    if (url.pathname === '/profile') return send(res, { profile: await getProfile() });
    return send(res, { error: 'unknown endpoint', available: ['/all', '/games', '/achievements', '/profile'] }, 404);
  } catch (error) {
    return send(res, { error: error.message }, 500);
  }
});
server.listen(PORT, () => {
  console.log(`Steam API listening on http://localhost:${PORT}`);
});

async function getAll() {
  const profile = await getProfile();
  const games = await getGamesData();
  const achievements = games.error ? { count: 0, games: [], scanned: 0, error: games.error } : await getCompletedGames(games.games);
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
  if (!STEAM_API_KEY) {
    return {
      count: 0,
      totalHours: 0,
      top10: [],
      games: [],
      error: 'NO_API_KEY',
      message: '需要在 Railway 环境变量中配置 STEAM_API_KEY。',
    };
  }

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

async function getCompletedGamesFromOwnedGames() {
  const games = await getGamesData();
  if (games.error) return { count: 0, games: [], scanned: 0, error: games.error };
  return getCompletedGames(games.games);
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

  const response = await fetch(url);
  if (!response.ok) throw new Error(`Steam API ${path}: ${response.status}`);
  return response.json();
}

async function fetchXML(url) {
  const response = await fetch(url, {
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

function xmlGet(xml, tag) {
  const cdata = xml.match(new RegExp(`<${tag}><!\\[CDATA\\[([\\s\\S]*?)\\]\\]></${tag}>`));
  if (cdata) return cdata[1].trim();
  const match = xml.match(new RegExp(`<${tag}>([\\s\\S]*?)</${tag}>`));
  return match ? match[1].trim() : '';
}

function send(res, data, status = 200) {
  res.writeHead(status, CORS);
  res.end(data === null ? null : JSON.stringify(data));
}
