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
  category?: string;
  value: string;
  enabled?: boolean;
  options?: { value: string; label: string }[];
  description?: string;
  what?: string;
  who?: string;
};

type ScriptOption = {
  key: string;
  label: string;
  category: string;
  description: string;
  type?: "boolean" | "select";
  options?: string[];
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

async function apiForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(path, { method: "POST", body });
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

function HelpText({ description }: { description: string }) {
  return <p className="help">{description}</p>;
}

function SettingRow({ setting, value, onChange }: { setting: Setting; value: string; onChange: (value: string) => void }) {
  return (
    <div className="setting-row">
      <div>
        <h3>{setting.label}</h3>
        <HelpText description={setting.description || [setting.what, setting.who].filter(Boolean).join(" ")} />
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
        if (!danger || window.confirm("Are you sure you want to run this action?")) {
          Promise.resolve(onConfirm()).catch((err) => window.alert(String(err)));
        }
      }}
    >
      {children}
    </button>
  );
}

function JobLogPanel({ job }: { job: Job | null }) {
  if (!job) return <div className="log empty">No running job selected</div>;
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
      <option value="">Select a MiSTer</option>
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
        <HelpText description="These controls send commands directly to the active MiSTer profile. Use them for maintenance tasks such as toggling SMB, returning to the menu core, or rebooting after updates." />
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
        {Array.from(new Set(settings.map((setting) => setting.category || "General"))).map((category) => (
          <div className="settings-category" key={category}>
            <h2>{category}</h2>
            {settings.filter((setting) => (setting.category || "General") === category).map((setting) => (
              <SettingRow key={setting.key} setting={setting} value={values[setting.key] ?? ""} onChange={(value) => setValues({ ...values, [setting.key]: value })} />
            ))}
          </div>
        ))}
      </div>
      <AdvancedPanel data={raw} label="Advanced raw INI" />
    </section>
  );
}

const scriptOptions: ScriptOption[] = [
  { key: "main_cores", label: "Official MiSTer cores", category: "Core sources", description: "Keeps the standard MiSTer-devel cores up to date. Most users should keep this enabled." },
  { key: "jtcores", label: "Jotego arcade cores", category: "Core sources", description: "Downloads Jotego arcade cores and related files. Enable this if you play Jotego arcade releases." },
  { key: "jt_beta", label: "Jotego beta cores", category: "Core sources", description: "Allows beta Jotego cores in update_all. Use this when you support Jotego and want early access builds." },
  { key: "coinop", label: "Coin-Op Collection", category: "Core sources", description: "Adds Coin-Op Collection arcade content. Useful for arcade-focused installations." },
  { key: "unofficial", label: "Unofficial cores", category: "Core sources", description: "Adds the community unofficial MiSTer distribution. Enable it if you deliberately want experimental or non-mainline cores." },
  { key: "mister_frontier", label: "MiSTer Frontier", category: "Core sources", description: "Adds MiSTer Frontier cores such as PICO-8 and OpenBOR. Pick this when you want those newer platform-style cores managed by update_all." },
  { key: "arcade_roms", label: "Arcade ROM database", category: "Games and BIOS", description: "Lets update_all download required arcade ROM files from the configured arcade database sources." },
  { key: "bios", label: "BIOS database", category: "Games and BIOS", description: "Downloads BIOS files used by supported cores. This is helpful on fresh setups, but review local legal requirements." },
  { key: "bootroms", label: "Boot ROM launchers", category: "Games and BIOS", description: "Adds MGL launchers for boot ROM based systems. Use it if you want cleaner launching for ROM-oriented cores." },
  { key: "gbaborders", label: "GBA borders", category: "Games and BIOS", description: "Adds Game Boy Advance border artwork. Enable this if you use handheld cores and want curated borders." },
  { key: "insert_coin", label: "Insert Coin assets", category: "Games and BIOS", description: "Adds Insert Coin artwork and related arcade polish for supported setups." },
  { key: "arcade_org", label: "Arcade Organizer", category: "Organization", description: "Organizes arcade files into friendlier names and folders. Enable it if you want curated arcade browsing rather than raw core filenames." },
  { key: "arcade_offset", label: "Arcade offset folder", category: "Organization", description: "Adds alternate arcade folder organization data. Useful for cabinets or curated menu layouts." },
  { key: "llapi", label: "LLAPI folder", category: "Hardware support", description: "Adds LLAPI support files. Enable only if you use LLAPI-compatible controllers or adapters." },
  { key: "sam", label: "MiSTer SAM", category: "Hardware support", description: "Installs MiSTer SAM files for automatic/randomized game launching workflows." },
  { key: "tty2oled", label: "TTY2OLED", category: "Hardware support", description: "Downloads files for TTY2OLED displays. Enable this for external OLED status displays connected to your MiSTer setup." },
  { key: "i2c2oled", label: "I2C2OLED", category: "Hardware support", description: "Downloads files for I2C OLED display integrations. Only enable it when you use that hardware." },
  { key: "retrospy", label: "RetroSpy", category: "Hardware support", description: "Adds RetroSpy support files for controller input visualization and streaming overlays." },
  { key: "anime0t4ku_mister_scripts", label: "Anime0t4ku scripts", category: "Community scripts", description: "Adds the companion script database used by several convenience features in this app." },
  { key: "anime0t4ku_wallpapers", label: "Anime0t4ku wallpapers", category: "Wallpapers", description: "Downloads the Anime0t4ku wallpaper collection through update_all." },
  { key: "pcn_challenge_wallpapers", label: "PCN challenge wallpapers", category: "Wallpapers", description: "Adds the PCN challenge wallpaper pack. Enable this if you want that curated artwork set." },
  { key: "pcn_premium_wallpapers", label: "PCN premium wallpapers", category: "Wallpapers", description: "Adds the PCN premium wallpaper pack. Use it only if that source is part of your setup." },
  { key: "ranny_wallpapers", label: "Ranny-Snice wallpapers", category: "Wallpapers", description: "Adds the Ranny-Snice wallpaper repository. You can choose all wallpapers or filter by aspect ratio." },
  { key: "manualsdb", label: "Manuals database", category: "Documentation", description: "Downloads game manuals database files so supported frontends can show manuals alongside games." },
];

function ScriptsTab({ setJob, job }: { setJob: (job: Job) => void; job: Job | null }) {
  const [status, setStatus] = useState<any>({});
  const [config, setConfig] = useState<Record<string, any>>({});
  const [configError, setConfigError] = useState("");
  const refresh = () => api<any>("/api/scripts/status").then(setStatus).catch((e) => setStatus({ error: String(e) }));
  const loadConfig = () => api<{ available: boolean; values: Record<string, any>; error?: string }>("/api/scripts/config")
    .then((data) => {
      setConfig(data.values || {});
      setConfigError(data.available ? "" : data.error || "update_all configuration is not available yet.");
    })
    .catch((e) => setConfigError(String(e)));
  const run = (key: string) => api<Job>("/api/scripts/run", { method: "POST", body: JSON.stringify({ key }) }).then(setJob);
  const saveConfig = () => api<{ values: Record<string, any> }>("/api/scripts/config", { method: "POST", body: JSON.stringify({ values: config }) }).then((data) => setConfig(data.values || {}));
  useEffect(() => { refresh(); loadConfig(); }, []);
  const scripts = [
    ["update_all", "Update All", "Updates cores, scripts, databases, BIOS packs, wallpapers, and optional community sources selected below."],
    ["zaparoo", "Zaparoo", "Runs the Zaparoo helper script for NFC/card-driven launching workflows."],
    ["auto_time", "Auto Time", "Runs the time synchronization helper for MiSTers without a reliable RTC."],
  ];
  return (
    <div className="grid two scripts-grid">
      <section>
        <h2>Scripts</h2>
        <div className="card-list">
          {scripts.map(([key, label, description]) => (
            <div className="action-card" key={key}>
              <div><h3>{label}</h3><HelpText description={description} /></div>
              <button onClick={() => run(key)}><Play size={16} />Run</button>
            </div>
          ))}
        </div>
        <h2>Live Terminal</h2>
        <p className="help">When you run a script, its output streams here so you can follow progress, warnings, download errors, and final success or failure without leaving the WebGUI.</p>
        <JobLogPanel job={job} />
      </section>
      <section>
        <div className="toolbar">
          <h2>update_all Options</h2>
          <button onClick={() => { refresh(); loadConfig(); }}><RefreshCw size={16} />Refresh</button>
          <button onClick={saveConfig}><Save size={16} />Save Options</button>
        </div>
        {configError && <p className="error">{configError}</p>}
        <div className="settings-list compact">
          {Array.from(new Set(scriptOptions.map((option) => option.category))).map((category) => (
            <div className="settings-category" key={category}>
              <h2>{category}</h2>
              {scriptOptions.filter((option) => option.category === category).map((option) => (
                <div className="setting-row" key={option.key}>
                  <div><h3>{option.label}</h3><HelpText description={option.description} /></div>
                  <label className="switch">
                    <input type="checkbox" checked={Boolean(config[option.key])} onChange={(event) => setConfig({ ...config, [option.key]: event.target.checked })} />
                    <span>{config[option.key] ? "Yes" : "No"}</span>
                  </label>
                </div>
              ))}
            </div>
          ))}
        </div>
        <h2>Detected Script Status</h2>
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
        <HelpText description="The removable-device scan is handled by the Proxmox flash helper, so the WebGUI only offers USB or SD devices that the helper has whitelisted. Use this flow when preparing a fresh MiSTer SD card." />
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
      <HelpText description="SaveManager copies saves, and optionally savestates, into the persistent data volume. Use it before updates, SD card work, or experiments that might change your MiSTer storage." />
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
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const refresh = () => api<any>("/api/wallpapers/status").then(setData).catch((e) => setData({ error: String(e) }));
  useEffect(() => { refresh(); }, []);
  async function uploadFiles(files: FileList | File[]) {
    setUploading(true);
    setMessage("");
    try {
      for (const file of Array.from(files)) {
        const body = new FormData();
        body.append("file", file);
        await apiForm("/api/wallpapers/upload", body);
      }
      setMessage("Upload complete");
      await refresh();
    } catch (err) {
      setMessage(String(err));
    } finally {
      setUploading(false);
    }
  }
  return (
    <section className="full">
      <h2>Wallpapers</h2>
      <HelpText description="Drop JPG or PNG menu wallpapers here and the WebGUI uploads them to /media/fat/wallpapers on the active MiSTer profile. For a standard 16:9 menu setup, use 1920x1080 JPG files; 1280x720 also works, but 1080p gives the cleanest result on most HDMI displays." />
      <div
        className="dropzone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          uploadFiles(event.dataTransfer.files);
        }}
      >
        <Image size={28} />
        <strong>Drop wallpaper JPG/PNG files here</strong>
        <span>Recommended: 1920x1080 JPG, sRGB, under 25 MB per file.</span>
        <input type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" multiple onChange={(event) => event.target.files && uploadFiles(event.target.files)} />
      </div>
      {message && <p className={message.includes("Error") ? "error" : "notice"}>{message}</p>}
      {uploading && <p className="notice">Uploading...</p>}
      <div className="stat-grid">
        <div><strong>Count</strong><p>{data.count ?? "Unknown"}</p></div>
        <div><strong>Path</strong><p>{data.path || data.error || "Unknown"}</p></div>
      </div>
      <button onClick={refresh}><RefreshCw size={16} />Refresh</button>
      <AdvancedPanel data={data} />
    </section>
  );
}

function ExtrasTab({ setJob }: { setJob: (job: Job) => void }) {
  const [data, setData] = useState<Record<string, boolean>>({});
  const refresh = () => api<Record<string, boolean>>("/api/extras/status").then(setData).catch((e) => setData({ error: Boolean(String(e)) } as any));
  useEffect(() => { refresh(); }, []);
  const extras = [
    {
      key: "zaparoo_launcher",
      label: "Zaparoo Launcher",
      guidance: "Installs the launcher files used by Zaparoo/NFC workflows. Nothing needs to be dragged in; the installer downloads the release files and places them on the MiSTer.",
      steps: ["Connect to the MiSTer profile.", "Click Install or Update.", "Watch the terminal job until it finishes.", "Use the Zaparoo tab or NFC workflow after install."],
    },
    {
      key: "ra_cores",
      label: "RetroAchievements cores",
      guidance: "Downloads and installs the RetroAchievements-enabled core set. This is a managed download/install flow, not a drag-and-drop ZIP upload.",
      steps: ["Make sure RetroAchievements credentials are configured.", "Click Install or Update.", "Let the job download and place cores.", "Run update_all later if you also want databases refreshed."],
    },
    {
      key: "sonic_mania",
      label: "Sonic Mania",
      guidance: "Installs the MiSTer Sonic Mania support files. Some game data may still need to be supplied by you depending on the upstream project requirements; the WebGUI installer explains progress in the job log.",
      steps: ["Click Install or Update.", "Read the job log for required files or next steps.", "If the log asks for game data, copy the legally obtained files to the path it names.", "Refresh status after completion."],
    },
    {
      key: "three_s_arm",
      label: "Street Fighter III 3S ARM",
      guidance: "Installs or updates the 3S-ARM launcher/core integration. The installer downloads the public release assets and updates MiSTer.ini where needed.",
      steps: ["Click Install or Update.", "Watch the terminal job.", "If migration from legacy 3SX is detected, let the installer finish.", "Refresh status and launch from the MiSTer menu."],
    },
  ];
  const runAction = (key: string, action: "install" | "uninstall") =>
    api<Job>("/api/extras/action", { method: "POST", body: JSON.stringify({ key, action }) }).then(setJob).then(refresh);
  return (
    <section className="full">
      <h2>Extras</h2>
      <div className="card-list">
        {extras.map((extra) => (
          <div className="extra-card" key={extra.key}>
            <div>
              <h3>{extra.label}</h3>
              <HelpText description={extra.guidance} />
              <ol>
                {extra.steps.map((step) => <li key={step}>{step}</li>)}
              </ol>
            </div>
            <div className="extra-actions">
              <StatusBadge ok={Boolean(data[extra.key])} label={data[extra.key] ? "Installed" : "Not installed"} />
              <button onClick={() => runAction(extra.key, "install")}><Download size={16} />Install or Update</button>
              <ConfirmAction danger onConfirm={() => runAction(extra.key, "uninstall")}><Trash2 size={16} />Uninstall</ConfirmAction>
            </div>
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
        <HelpText description="RetroAchievements uses the configured account and API key to show your current profile summary and recent activity without exposing the stored secret values in the UI." />
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
    ["menu", "Home", "Loads the MiSTer menu core so you can return to the main navigation quickly."],
    ["osd", "OSD", "Triggers the on-screen display, useful when you are operating the MiSTer without a keyboard nearby."],
    ["bluetooth", "Bluetooth", "Starts the Bluetooth helper action for controller and accessory pairing workflows."],
    ["wallpaper", "Wallpaper", "Asks MiSTer to refresh or rotate the menu wallpaper so you can verify artwork changes immediately."],
  ];
  return (
    <section>
      <h2>ZapScripts</h2>
      <div className="card-list">
        {actions.map(([command, label, description]) => (
          <div className="action-card" key={command}>
            <div><h3>{label}</h3><HelpText description={description} /></div>
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
      <HelpText description="The manuals area prepares the local cache used for manual lookups. It is meant for browsing core or game documentation directly from the WebGUI once the upstream manuals database is populated." />
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
    if (active === "Scripts") return <ScriptsTab setJob={setJob} job={job} />;
    if (active === "Flash SD") return <FlashTab setJob={setJob} />;
    if (active === "ZapScripts") return <ZapScripts />;
    if (active === "SaveManager") return <SaveManagerTab setJob={setJob} />;
    if (active === "Wallpapers") return <WallpapersTab />;
    if (active === "Extras") return <ExtrasTab setJob={setJob} />;
    if (active === "RetroAchievements") return <RetroAchievementsTab />;
    if (active === "Manuals") return <ManualsTab />;
    return null;
  }, [active, job]);

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
