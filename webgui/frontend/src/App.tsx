import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Cable,
  CheckCircle2,
  Cpu,
  Download,
  FileSliders,
  Gamepad2,
  HardDrive,
  History,
  Image,
  Info,
  Play,
  Plus,
  Power,
  RefreshCw,
  Save,
  Search,
  Settings,
  ShieldAlert,
  Terminal,
  Trash2,
  Upload,
} from "lucide-react";
import "./styles.css";

type Health = {
  ok: boolean;
  app: string;
  upstream_version: string;
  connected: boolean;
  mode: "online" | "offline";
  offline_sd_root: string;
  active_profile_id?: string;
  import_error?: string;
};

type Job = {
  id: string;
  label: string;
  status: string;
  logs: string[];
  error?: string;
};

type Profile = {
  id: string;
  name: string;
  host: string;
  username: string;
  has_password?: boolean;
  use_ssh_agent?: boolean;
  look_for_ssh_keys?: boolean;
};

type ProfilePayload = {
  active_profile_id: string;
  profiles: Profile[];
};

type Setting = {
  key: string;
  label: string;
  type: "select" | "checkbox" | "text";
  value: string;
  enabled?: boolean;
  options?: { value: string; label: string }[];
  what: string;
  who: string;
};

const tabs = [
  { name: "Flash SD", asset: "flash_sd.svg", Icon: HardDrive },
  { name: "Connection", asset: "connection.svg", Icon: Cable },
  { name: "Device", asset: "device.svg", Icon: Cpu },
  { name: "MiSTer Settings", asset: "mister_settings.svg", Icon: FileSliders },
  { name: "Scripts", asset: "scripts.svg", Icon: Terminal },
  { name: "ZapScripts", asset: "zapscripts.svg", Icon: Gamepad2 },
  { name: "SaveManager", asset: "savemanager.svg", Icon: Save },
  { name: "Wallpapers", asset: "wallpapers.svg", Icon: Image },
  { name: "Extras", asset: "extras.svg", Icon: Settings },
  { name: "RetroAchievements", asset: "zapscripts.svg", Icon: History },
  { name: "Manuals", asset: "extras.svg", Icon: Info },
] as const;

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

function asList(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const refresh = () =>
    api<Health>("/api/health")
      .then((data) => {
        setHealth(data);
        setError("");
      })
      .catch((err) => setError(String(err)));
  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 5000);
    return () => window.clearInterval(id);
  }, []);
  return { health, error, refresh };
}

function StatusBadge({ ok, label }: { ok: boolean; label: string }) {
  return <span className={ok ? "badge ok" : "badge"}>{label}</span>;
}

function AdvancedPanel({ data, label = "Advanced" }: { data: unknown; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="advanced">
      <button type="button" onClick={() => setOpen(!open)}>
        <ShieldAlert size={15} />{open ? "Hide" : label}
      </button>
      {open ? <pre className="json">{typeof data === "string" ? data : JSON.stringify(data, null, 2)}</pre> : null}
    </div>
  );
}

function HelpText({ what, who }: { what: string; who: string }) {
  return (
    <p className="help">
      <strong>Wat doet dit?</strong> {what}<br />
      <strong>Voor wie?</strong> {who}
    </p>
  );
}

function SettingRow({ setting, value, onChange }: { setting: Setting; value: string; onChange: (value: string) => void }) {
  return (
    <div className="setting-row">
      <div>
        <h3>{setting.label}</h3>
        <HelpText what={setting.what} who={setting.who} />
      </div>
      {setting.type === "checkbox" ? (
        <label className="switch">
          <input
            type="checkbox"
            checked={value === "1" || value === "true"}
            onChange={(event) => onChange(event.target.checked ? "1" : "0")}
          />
          <span>{value === "1" || value === "true" ? "On" : "Off"}</span>
        </label>
      ) : setting.type === "select" ? (
        <select value={value} onChange={(event) => onChange(event.target.value)}>
          <option value="">Current / unset</option>
          {(setting.options || []).map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      ) : (
        <input value={value} onChange={(event) => onChange(event.target.value)} placeholder="Not set" />
      )}
    </div>
  );
}

function ConfirmAction({
  children,
  danger,
  onConfirm,
}: {
  children: React.ReactNode;
  danger?: boolean;
  onConfirm: () => Promise<unknown> | unknown;
}) {
  return (
    <button
      className={danger ? "danger" : ""}
      onClick={() => {
        if (!danger || window.confirm("Weet je zeker dat je deze actie wilt uitvoeren?")) {
          Promise.resolve(onConfirm()).catch((err) => window.alert(String(err)));
        }
      }}
    >
      {children}
    </button>
  );
}

function JobLogPanel({ job }: { job: Job | null }) {
  if (!job) return <div className="log empty">Geen job geselecteerd</div>;
  return (
    <div className="log">
      <div className="log-head">
        <span>{job.label}</span>
        <strong>{job.status}</strong>
      </div>
      <pre>{job.logs.join("\n")}</pre>
    </div>
  );
}

function ProfileSelector({
  value,
  profiles,
  onChange,
}: {
  value: string;
  profiles: Profile[];
  onChange: (id: string) => void;
}) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="">Selecteer MiSTer</option>
      {profiles.map((profile) => (
        <option key={profile.id} value={profile.id}>{profile.name} ({profile.host})</option>
      ))}
    </select>
  );
}

function ConnectionTab({ onRefresh }: { onRefresh: () => void }) {
  const [payload, setPayload] = useState<ProfilePayload>({ active_profile_id: "", profiles: [] });
  const [editingId, setEditingId] = useState("");
  const [form, setForm] = useState({ name: "MiSTer", host: "192.168.2.186", username: "root", password: "", use_ssh_agent: false, look_for_ssh_keys: false });
  const [scan, setScan] = useState<any[]>([]);
  const [message, setMessage] = useState("");

  const load = () => api<ProfilePayload>("/api/profiles").then(setPayload);
  useEffect(() => { load().catch((err) => setMessage(String(err))); }, []);

  function edit(profile: Profile) {
    setEditingId(profile.id);
    setForm({
      name: profile.name || "MiSTer",
      host: profile.host || "",
      username: profile.username || "root",
      password: "",
      use_ssh_agent: Boolean(profile.use_ssh_agent),
      look_for_ssh_keys: Boolean(profile.look_for_ssh_keys),
    });
  }

  async function saveProfile() {
    const method = editingId ? "PUT" : "POST";
    const path = editingId ? `/api/profiles/${editingId}` : "/api/profiles";
    const next = await api<ProfilePayload>(path, { method, body: JSON.stringify(form) });
    setPayload(next);
    setMessage("Profile saved");
  }

  async function connectProfile(id = payload.active_profile_id) {
    await api(`/api/profiles/${id}/connect`, { method: "POST" });
    await load();
    onRefresh();
    setMessage("Connected");
  }

  return (
    <div className="grid two">
      <section>
        <h2>Connection Profiles</h2>
        <ProfileSelector
          value={payload.active_profile_id}
          profiles={payload.profiles}
          onChange={(id) => api("/api/profiles/active", { method: "PUT", body: JSON.stringify({ id }) }).then(load)}
        />
        <div className="actions">
          <button onClick={() => connectProfile()} disabled={!payload.active_profile_id}><Cable size={16} />Connect</button>
          <button onClick={() => api("/api/disconnect", { method: "POST" }).then(onRefresh)}><Power size={16} />Disconnect</button>
          <button onClick={() => api<any[]>("/api/network/scan").then(setScan)}><Search size={16} />Scan</button>
        </div>
        <div className="profile-list">
          {payload.profiles.map((profile) => (
            <div className="profile-card" key={profile.id}>
              <div>
                <h3>{profile.name}</h3>
                <p>{profile.host} · {profile.username} · {profile.has_password ? "password stored" : "no password stored"}</p>
              </div>
              <div className="actions">
                <button onClick={() => edit(profile)}>Edit</button>
                <button onClick={() => connectProfile(profile.id)}><Cable size={15} />Use</button>
                <ConfirmAction danger onConfirm={() => api(`/api/profiles/${profile.id}`, { method: "DELETE" }).then(load)}>
                  <Trash2 size={15} />Delete
                </ConfirmAction>
              </div>
            </div>
          ))}
        </div>
        {message && <p className="notice">{message}</p>}
      </section>
      <section>
        <h2>{editingId ? "Edit Profile" : "Add Profile"}</h2>
        <label>Name<input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label>Host<input value={form.host} onChange={(e) => setForm({ ...form, host: e.target.value })} /></label>
        <label>User<input autoComplete="username" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label>Password<input type="password" autoComplete="current-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="Leave empty to clear" /></label>
        <label className="checkline"><input type="checkbox" checked={form.use_ssh_agent} onChange={(e) => setForm({ ...form, use_ssh_agent: e.target.checked })} /> Use SSH agent</label>
        <label className="checkline"><input type="checkbox" checked={form.look_for_ssh_keys} onChange={(e) => setForm({ ...form, look_for_ssh_keys: e.target.checked })} /> Look for SSH keys</label>
        <div className="actions">
          <button onClick={saveProfile}><Save size={16} />Save</button>
          <button onClick={() => { setEditingId(""); setForm({ name: "MiSTer", host: "", username: "root", password: "", use_ssh_agent: false, look_for_ssh_keys: false }); }}><Plus size={16} />New</button>
        </div>
        {scan.length ? (
          <>
            <h2>Network Scan</h2>
            <div className="list">{scan.map((item) => <button key={item.host} onClick={() => setForm({ ...form, host: item.host })}>{item.host}</button>)}</div>
          </>
        ) : null}
      </section>
    </div>
  );
}

function DeviceTab() {
  const [info, setInfo] = useState<any>(null);
  const refresh = () => api<any>("/api/device/info").then(setInfo).catch((e) => setInfo({ error: String(e) }));
  useEffect(() => { refresh(); }, []);
  const sdPercent = Number(info?.sd?.percent || info?.sd?.used_percent || 0);
  return (
    <div className="grid two">
      <section>
        <h2>Storage</h2>
        <button onClick={refresh}><RefreshCw size={16} />Refresh</button>
        <div className="meter"><span style={{ width: `${Math.max(0, Math.min(100, sdPercent))}%` }} /></div>
        <div className="stat-grid">
          <div><strong>SD</strong><p>{info?.sd?.label || info?.error || "No storage data"}</p></div>
          <div><strong>USB</strong><p>{info?.usb?.label || "No USB storage data"}</p></div>
          <div><strong>SMB</strong><p>{info?.smb_enabled ? "Enabled" : "Disabled"}</p></div>
        </div>
        <AdvancedPanel data={info} />
      </section>
      <section>
        <h2>Device Actions</h2>
        <HelpText what="Deze acties sturen direct commando's naar de actieve MiSTer." who="Voor onderhoud, snelle reboot of terugkeren naar het MiSTer menu." />
        <div className="actions">
          <button onClick={() => api("/api/device/smb", { method: "POST", body: JSON.stringify({ enabled: !info?.smb_enabled }) }).then(refresh)}>
            <Upload size={16} />SMB {info?.smb_enabled ? "Off" : "On"}
          </button>
          <button onClick={() => api("/api/device/return-to-menu", { method: "POST" })}><Gamepad2 size={16} />Menu</button>
          <ConfirmAction danger onConfirm={() => api("/api/device/reboot", { method: "POST" })}><Power size={16} />Reboot</ConfirmAction>
        </div>
      </section>
    </div>
  );
}

function SettingsTab() {
  const [files, setFiles] = useState<string[]>([]);
  const [path, setPath] = useState("MiSTer.ini");
  const [settings, setSettings] = useState<Setting[]>([]);
  const [values, setValues] = useState<Record<string, string>>({});
  const [raw, setRaw] = useState("");
  const [message, setMessage] = useState("");
  const loadFiles = () => api<string[]>("/api/ini").then((items) => { setFiles(items); if (items[0]) setPath(items[0]); });
  const loadSchema = (p = path) =>
    api<{ settings: Setting[]; raw: string }>("/api/ini/schema?path=" + encodeURIComponent(p)).then((data) => {
      setSettings(data.settings);
      setRaw(data.raw);
      setValues(Object.fromEntries(data.settings.map((item) => [item.key, item.type === "checkbox" ? (item.enabled ? "1" : "0") : item.value || ""])));
    });
  useEffect(() => { loadFiles().catch(() => {}); }, []);
  useEffect(() => { if (path) loadSchema(path).catch((err) => setMessage(String(err))); }, [path]);
  return (
    <section className="full">
      <div className="toolbar">
        <select value={path} onChange={(e) => setPath(e.target.value)}>{files.map((f) => <option key={f}>{f}</option>)}</select>
        <button onClick={() => loadSchema()}><RefreshCw size={16} />Reload</button>
        <button onClick={() => api<{ settings: Setting[]; raw: string }>("/api/ini/settings", { method: "POST", body: JSON.stringify({ path, values }) }).then((data) => { setSettings(data.settings); setRaw(data.raw); setMessage("Saved"); })}><Save size={16} />Save</button>
        <span>{message}</span>
      </div>
      <div className="settings-list">
        {settings.map((setting) => (
          <SettingRow key={setting.key} setting={setting} value={values[setting.key] ?? ""} onChange={(value) => setValues({ ...values, [setting.key]: value })} />
        ))}
      </div>
      <AdvancedPanel data={raw} label="Advanced raw INI" />
    </section>
  );
}

function ScriptsTab({ setJob }: { setJob: (job: Job) => void }) {
  const [status, setStatus] = useState<any>({});
  const refresh = () => api<any>("/api/scripts/status").then(setStatus).catch((e) => setStatus({ error: String(e) }));
  const run = (key: string) => api<Job>("/api/scripts/run", { method: "POST", body: JSON.stringify({ key }) }).then(setJob);
  useEffect(() => { refresh(); }, []);
  const scripts = [
    ["update_all", "Update All", "Update cores, scripts and databases.", "Voor normaal MiSTer onderhoud."],
    ["zaparoo", "Zaparoo", "Start of update Zaparoo script support.", "Voor NFC/cards en launcher workflows."],
    ["auto_time", "Auto Time", "Synchroniseert tijd via script.", "Voor MiSTers zonder betrouwbare RTC."],
  ];
  return (
    <div className="grid two">
      <section>
        <h2>Scripts</h2>
        <div className="card-list">
          {scripts.map(([key, label, what, who]) => (
            <div className="action-card" key={key}>
              <div><h3>{label}</h3><HelpText what={what} who={who} /></div>
              <button onClick={() => run(key)}><Play size={16} />Run</button>
            </div>
          ))}
        </div>
      </section>
      <section>
        <h2>Status</h2>
        <button onClick={refresh}><RefreshCw size={16} />Refresh</button>
        <div className="stat-grid">
          {Object.entries(status).filter(([, value]) => typeof value !== "object").map(([key, value]) => (
            <div key={key}><strong>{key}</strong><p>{String(value)}</p></div>
          ))}
        </div>
        <AdvancedPanel data={status} />
      </section>
    </div>
  );
}

function FlashTab({ setJob }: { setJob: (job: Job) => void }) {
  const [devices, setDevices] = useState<any[]>([]);
  const [releases, setReleases] = useState<any>({});
  const [error, setError] = useState("");
  const refresh = () => api<any[]>("/api/flash/devices").then(setDevices).then(() => setError("")).catch((e) => setError(String(e)));
  useEffect(() => {
    refresh();
    api<any>("/api/flash/releases").then(setReleases).catch((e) => setReleases({ error: String(e) }));
  }, []);
  return (
    <div className="grid two">
      <section>
        <h2>Flash SD</h2>
        <HelpText what="Scant alleen removable USB/SD-devices via de Proxmox helper." who="Voor het veilig voorbereiden van een nieuwe MiSTer SD-kaart." />
        <div className="actions">
          <button onClick={refresh}><RefreshCw size={16} />Devices</button>
          <button onClick={() => api<Job>("/api/flash/download", { method: "POST", body: JSON.stringify({ source: "mr-fusion" }) }).then(setJob)}><Download size={16} />Mr. Fusion</button>
          <button onClick={() => api<Job>("/api/flash/download", { method: "POST", body: JSON.stringify({ source: "superstation" }) }).then(setJob)}><Download size={16} />SuperStation</button>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="card-list">
          {devices.length ? devices.map((device) => (
            <div className="action-card" key={device.path}>
              <div><h3>{device.path}</h3><p>{device.size || device.size_human} · {device.model || "Removable device"}</p></div>
              <StatusBadge ok={Boolean(device.removable ?? true)} label="Removable" />
            </div>
          )) : <p>No removable devices detected</p>}
        </div>
      </section>
      <section>
        <h2>Releases</h2>
        <div className="card-list">
          {Object.entries(releases).map(([key, value]: [string, any]) => (
            <div className="action-card" key={key}>
              <div><h3>{key}</h3><p>{value?.name || value?.tag || value?.error || "Release info unavailable"}</p></div>
              <StatusBadge ok={!value?.error} label={value?.tag || "ready"} />
            </div>
          ))}
        </div>
        <AdvancedPanel data={releases} />
      </section>
    </div>
  );
}

function SaveManagerTab({ setJob }: { setJob: (job: Job) => void }) {
  const [backups, setBackups] = useState<string[]>([]);
  const refresh = () => api<string[]>("/api/savemanager/backups").then(setBackups).catch(() => setBackups([]));
  useEffect(() => { refresh(); }, []);
  return (
    <section className="full">
      <h2>SaveManager</h2>
      <HelpText what="Maakt backups van saves en optioneel savestates naar de persistente data-map." who="Voor iedereen die saves wil beschermen voor updates of SD-werk." />
      <div className="actions">
        <button onClick={() => api<Job>("/api/savemanager/backup?include_savestates=true", { method: "POST" }).then(setJob).then(refresh)}><Save size={16} />Backup saves + states</button>
        <button onClick={() => api<Job>("/api/savemanager/backup?include_savestates=false", { method: "POST" }).then(setJob).then(refresh)}><Save size={16} />Backup saves only</button>
        <button onClick={refresh}><RefreshCw size={16} />Refresh</button>
      </div>
      <div className="table-list">{backups.map((backup) => <div key={backup}><CheckCircle2 size={16} />{backup}</div>)}</div>
      <AdvancedPanel data={backups} />
    </section>
  );
}

function WallpapersTab() {
  const [data, setData] = useState<any>({});
  const refresh = () => api<any>("/api/wallpapers/status").then(setData).catch((e) => setData({ error: String(e) }));
  useEffect(() => { refresh(); }, []);
  return (
    <section className="full">
      <h2>Wallpapers</h2>
      <HelpText what="Toont hoeveel wallpapers op de MiSTer of offline SD-map gevonden zijn." who="Voor wie snel wil controleren of wallpaper assets aanwezig zijn." />
      <div className="stat-grid">
        <div><strong>Count</strong><p>{data.count ?? "Unknown"}</p></div>
        <div><strong>Path</strong><p>{data.path || data.error || "Unknown"}</p></div>
      </div>
      <button onClick={refresh}><RefreshCw size={16} />Refresh</button>
      <AdvancedPanel data={data} />
    </section>
  );
}

function ExtrasTab() {
  const [data, setData] = useState<Record<string, boolean>>({});
  const refresh = () => api<Record<string, boolean>>("/api/extras/status").then(setData).catch((e) => setData({ error: Boolean(String(e)) } as any));
  useEffect(() => { refresh(); }, []);
  const labels: Record<string, string> = {
    zaparoo_launcher: "Zaparoo Launcher",
    ra_cores: "RetroAchievements cores",
    sonic_mania: "Sonic Mania",
    three_s_arm: "Street Fighter III 3S",
  };
  return (
    <section className="full">
      <h2>Extras</h2>
      <div className="card-list">
        {Object.entries(data).map(([key, present]) => (
          <div className="action-card" key={key}>
            <div><h3>{labels[key] || key}</h3><HelpText what="Controleert of deze extra assets of scripts aanwezig zijn." who="Voor uitbreidingen buiten de standaard MiSTer installatie." /></div>
            <StatusBadge ok={Boolean(present)} label={present ? "Installed" : "Missing"} />
          </div>
        ))}
      </div>
      <button onClick={refresh}><RefreshCw size={16} />Refresh</button>
      <AdvancedPanel data={data} />
    </section>
  );
}

function RetroAchievementsTab() {
  const [config, setConfig] = useState<any>({});
  const [summary, setSummary] = useState<any>({});
  useEffect(() => {
    api<any>("/api/retroachievements/config").then(setConfig).catch((e) => setConfig({ error: String(e) }));
    api<any>("/api/retroachievements/summary").then(setSummary).catch((e) => setSummary({ error: String(e) }));
  }, []);
  const recentGames = asList(summary.recent_games).slice(0, 6) as any[];
  const achievements = asList(summary.recent_achievements).slice(0, 6) as any[];
  return (
    <div className="grid two">
      <section>
        <h2>RetroAchievements Account</h2>
        <div className="stat-grid">
          <div><strong>User</strong><p>{config.username || "Not configured"}</p></div>
          <div><strong>Password</strong><p>{config.has_password ? "Configured" : "Not stored"}</p></div>
          <div><strong>API key</strong><p>{config.has_api_key ? "Configured" : "Required"}</p></div>
        </div>
        <HelpText what="Gebruikt RetroAchievements API data om profielinformatie te tonen." who="Voor spelers die achievement-status naast hun MiSTer setup willen zien." />
      </section>
      <section>
        <h2>Viewer</h2>
        <StatusBadge ok={Boolean(summary.available)} label={summary.available ? "Available" : (summary.reason || "Unavailable")} />
        <div className="table-list">
          {recentGames.map((game, index) => <div key={index}><Gamepad2 size={16} />{game.title || game.Title || game.game_title || JSON.stringify(game)}</div>)}
          {achievements.map((item, index) => <div key={`a-${index}`}><History size={16} />{item.title || item.Title || item.achievement_title || JSON.stringify(item)}</div>)}
        </div>
        <AdvancedPanel data={summary} />
      </section>
    </div>
  );
}

function ZapScripts() {
  const send = (command: string) => api("/api/zapscripts/send", { method: "POST", body: JSON.stringify({ command }) });
  const actions = [
    ["menu", "Home", "Laadt het MiSTer menu.", "Voor snel terug naar de hoofdnavigatie."],
    ["osd", "OSD", "Opent of triggert de on-screen display.", "Voor bediening zonder keyboard."],
    ["bluetooth", "Bluetooth", "Start Bluetooth pairing/actie.", "Voor controllers en Bluetooth-accessoires."],
    ["wallpaper", "Wallpaper", "Wisselt wallpaper via MiSTer command.", "Voor snelle visuele check."],
  ];
  return (
    <section>
      <h2>ZapScripts</h2>
      <div className="card-list">
        {actions.map(([command, label, what, who]) => (
          <div className="action-card" key={command}>
            <div><h3>{label}</h3><HelpText what={what} who={who} /></div>
            <button onClick={() => send(command)}><Gamepad2 size={16} />Send</button>
          </div>
        ))}
      </div>
    </section>
  );
}

function ManualsTab() {
  const [data, setData] = useState<any>({});
  useEffect(() => { api<any>("/api/manuals").then(setData).catch((e) => setData({ error: String(e) })); }, []);
  return (
    <section className="full">
      <h2>Manuals</h2>
      <HelpText what="Bereidt de manual database/cache voor." who="Voor gebruikers die core- of game-handleidingen direct vanuit de WebGUI willen vinden." />
      <div className="stat-grid">
        <div><strong>Status</strong><p>{data.available ? "Ready" : data.error || "Unavailable"}</p></div>
        <div><strong>Cache</strong><p>{data.database_path || "Unknown"}</p></div>
      </div>
      <AdvancedPanel data={data} />
    </section>
  );
}

function App() {
  const { health, error, refresh } = useHealth();
  const [active, setActive] = useState("Connection");
  const [job, setJob] = useState<Job | null>(null);
  const [offlineRoot, setOfflineRoot] = useState("");

  useEffect(() => {
    if (!job || ["succeeded", "failed", "cancelled"].includes(job.status)) return;
    const id = window.setInterval(() => api<Job>("/api/jobs/" + job.id).then(setJob).catch(() => {}), 1000);
    return () => window.clearInterval(id);
  }, [job]);

  const content = useMemo(() => {
    if (active === "Connection") return <ConnectionTab onRefresh={refresh} />;
    if (active === "Device") return <DeviceTab />;
    if (active === "MiSTer Settings") return <SettingsTab />;
    if (active === "Scripts") return <ScriptsTab setJob={setJob} />;
    if (active === "Flash SD") return <FlashTab setJob={setJob} />;
    if (active === "ZapScripts") return <ZapScripts />;
    if (active === "SaveManager") return <SaveManagerTab setJob={setJob} />;
    if (active === "Wallpapers") return <WallpapersTab />;
    if (active === "Extras") return <ExtrasTab />;
    if (active === "RetroAchievements") return <RetroAchievementsTab />;
    if (active === "Manuals") return <ManualsTab />;
    return null;
  }, [active]);

  return (
    <main>
      <header className="titlebar">
        <div className="brand"><img src="/mc-assets/logo_2.png" alt="MiSTer Companion" /></div>
        <strong className="version">{health?.upstream_version || "loading"}</strong>
      </header>
      {error || health?.import_error ? <div className="banner">{error || health?.import_error}</div> : null}
      <div className="window">
        <nav className="tabs" aria-label="MiSTer Companion sections">
          {tabs.map(({ name, asset, Icon }) => (
            <button key={name} className={active === name ? "active" : ""} onClick={() => setActive(name)}>
              <img src={`/mc-assets/${asset}`} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} />
              <Icon className="fallback-icon" size={16} />
              <span>{name}</span>
            </button>
          ))}
        </nav>
        <div className="content">{content}</div>
        {job ? <div className="job-dock"><JobLogPanel job={job} /></div> : null}
      </div>
      <footer className="bottom-bar">
        <span className={health?.connected ? "status ok" : "status"}>Status: {health?.connected ? "Connected" : "Disconnected"}</span>
        <div className="mode">
          <input placeholder="/media/sdcard" value={offlineRoot} onChange={(e) => setOfflineRoot(e.target.value)} />
          <button onClick={() => api("/api/state/mode", { method: "POST", body: JSON.stringify({ mode: "offline", offline_sd_root: offlineRoot }) }).then(refresh)}>Offline</button>
          <button onClick={() => api("/api/state/mode", { method: "POST", body: JSON.stringify({ mode: "online", offline_sd_root: "" }) }).then(refresh)}>Online</button>
        </div>
        <button onClick={refresh}><RefreshCw size={15} />Check for Updates</button>
        <button onClick={() => window.open("https://github.com/Anime0t4ku/mister-companion", "_blank")}>Support</button>
        <button onClick={() => window.open("https://github.com/Anime0t4ku/mister-companion/issues/new/choose", "_blank")}>Feedback</button>
        <button onClick={() => setActive("ZapScripts")}>Remote</button>
        <button onClick={() => setActive("Manuals")}>Manuals</button>
        <button onClick={() => setActive("RetroAchievements")}>RetroAchievements</button>
        <select aria-label="UI Scale" defaultValue="100%"><option>100%</option><option>110%</option><option>120%</option></select>
        <select aria-label="Theme" defaultValue="Dark"><option>Auto</option><option>Light</option><option>Dark</option></select>
      </footer>
    </main>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
