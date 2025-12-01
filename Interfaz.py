

import os, socket, threading, time, random, uuid
import tkinter as tk
from tkinter import ttk, filedialog

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except Exception:
    PIL_OK = False

BASE = os.path.abspath(os.path.dirname(__file__))
HISTORY_FILE = os.path.join(BASE, "historial_partidas.txt")

# ------------------ Sonido ------------------
class Sounder:
    def __init__(self, base_dir):
        self.base = base_dir
        self.have_pygame = False
        self._ambient_on = False
        self._ambient_name = "7_Ambiente.mp3"
        try:
            import pygame
            pygame.mixer.init()
            self.pygame = pygame
            self.have_pygame = True
            print(f"pygame {pygame.version.ver} listo.")
        except Exception as e:
            self.pygame = None
            print("[SND] pygame no disponible:", e)
        try:
            import winsound  # noqa
            self.have_winsound = True
        except Exception:
            self.have_winsound = False
        self._cache = {}

    def _path(self, name):
        p = name if os.path.isabs(name) else os.path.join(self.base, name)
        return p if os.path.exists(p) else ""

    def fx(self, name):
        p = self._path(name)
        if not p:
            print(f"[SND] No existe {name}")
            return
        if self.have_pygame:
            try:
                snd = self._cache.get(p) or self.pygame.mixer.Sound(p)
                self._cache[p] = snd
                snd.play(); return
            except Exception as e:
                print("[SND] pygame FX error:", e)
        if self.have_winsound:
            try:
                import winsound
                winsound.PlaySound(p, winsound.SND_FILENAME | winsound.SND_ASYNC)
            except Exception as e:
                print("[SND] winsound FX error:", e)

    def ambient_start(self, filename=None):
        if filename: self._ambient_name = filename
        p = self._path(self._ambient_name)
        if not p:
            print(f"[SND] Ambiente no encontrado: {self._ambient_name}")
            self._ambient_on = False; return
        self._ambient_on = True
        if self.have_pygame:
            try:
                self.pygame.mixer.music.load(p)
                self.pygame.mixer.music.play(loops=-1); return
            except Exception as e:
                print("[SND] pygame music error:", e)
        if self.have_winsound:
            try:
                import winsound
                winsound.PlaySound(p, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
            except Exception as e:
                print("[SND] winsound loop error:", e)

    def ambient_stop(self):
        self._ambient_on = False
        if self.have_pygame:
            try: self.pygame.mixer.music.stop()
            except Exception: pass
        if self.have_winsound:
            try:
                import winsound
                winsound.PlaySound(None, 0)
            except Exception: pass

    @property
    def ambient_on(self):
        return self._ambient_on

def s_connect():    S.fx("5_conectar.mp3")
def s_transition(): S.fx("6_Transicion.mp3")
def s_whistle_go(): S.fx("1_pito_start.mp3")
def s_boo():        S.fx("3_abucheo.mp3")
def s_goal():       S.fx("4_gol.mp3")

# ------------------ Imágenes ------------------
def find_file(prefix):
    for ext in (".gif", ".png", ".jpg", ".jpeg"):
        p = os.path.join(BASE, prefix+ext)
        if os.path.exists(p): return p
    return ""

def load_img(path):
    if not path: return None
    if not os.path.isabs(path): path = os.path.join(BASE, path)
    if not os.path.exists(path):
        if 'app' in globals() and app: app.log(f"[IMG] No existe: {os.path.basename(path)}")
        return None
    try:
        if PIL_OK:
            im = Image.open(path); im.load()
            return ImageTk.PhotoImage(im)
        return tk.PhotoImage(file=path)
    except Exception as e:
        if 'app' in globals() and app: app.log(f"[IMG] Error: {e}")
        return None

def cargar_img_cuadrada(nombre, lado=256):
    p = find_file(nombre)
    if not p: return None
    try:
        if PIL_OK:
            im = Image.open(p).convert("RGBA")
            im = im.resize((lado, lado), Image.LANCZOS)
            return ImageTk.PhotoImage(im)
        return tk.PhotoImage(file=p)
    except Exception as e:
        if 'app' in globals() and app: app.log(f"[IMG] Error cargando {nombre}: {e}")
        return None

# ------------------ Estado ------------------
PALETA_IDX = {"A":0,"B":1,"C":2,"D":3,"E":4,"F":5}

class Game:
    def __init__(self):
        self.name  = ["Jugador 1", "Jugador 2"]
        self.ppath = [find_file("Jugador1"), find_file("Jugador2")]
        self.photo = [None, None]
        self.teams = []
        for i in range(1, 10):
            p = find_file(f"Escudo{i}")
            if p: self.teams.append((f"Equipo {chr(64+i)}", p))
        if len(self.teams) < 2: self.teams += [("Equipo A",""), ("Equipo B","")]
        self.team_idx = [0, 1]
        self.badge = [None, None]
        self.goals = [0,0]
        self.first = 0
        self.active = 0
        self.gk_bits = [False]*6
        self.max_intentos = 5
        self.intentos = [0, 0]
        self.fallos   = [0, 0]
        # Historial en memoria, única entrada por partida:
        self.history = []          # lista visible en UI
        self.history_map = {}      # match_id -> entry
        self.match_id = None

    def set_team(self, j, idx):
        self.team_idx[j] = idx
        path = self.teams[idx][1]
        self.badge[j] = load_img(path) if path else None

    def reset_match(self):
        self.goals    = [0, 0]
        self.intentos = [0, 0]
        self.fallos   = [0, 0]
        self.gk_bits  = [False]*6
        self.match_id = str(uuid.uuid4())

    @property
    def total_intentos(self):
        return self.intentos[0] + self.intentos[1]

    def match_over(self):
        return self.intentos[0] >= self.max_intentos and self.intentos[1] >= self.max_intentos

G = Game()

# ------------------ TCP ------------------
HOST = "192.168.6.189"
PORT = 8001
_VALID_ONECHAR = set("ABCDEF") | set("GHI")

def _tokens_from_bytes(buf: bytes):
    text = ""
    try: text = buf.decode(errors="ignore")
    except Exception: pass
    had_line = False
    for raw in text.replace("\r", "").split("\n"):
        if not raw: continue
        had_line = True
        line = raw.strip()
        if line.startswith("GK:"): 
            yield line; continue
        if len(line) == 1 and line in _VALID_ONECHAR:
            yield line; continue
    if not had_line:
        for ch in text:
            if ch in _VALID_ONECHAR: yield ch

def _parse_gk(payload: str):
    data = payload[3:].strip().lower()
    bits = [False]*6
    try:
        if len(data) >= 6 and set(data[:6]).issubset({"0","1"}):
            return [c=="1" for c in data[:6]]
        v = int(data, 16) if data.startswith("0x") else int(data)
        for i in range(6): bits[i] = bool((v >> i) & 1)
        return bits
    except Exception:
        return None

# ------------------ Persistencia en memoria/archivo ------------------
def _upsert_history_memory(entry):
    """Mantiene UNA sola entrada por match_id en la memoria (UI)."""
    mid = entry.get("id","")
    if not mid:
        return
    prev = G.history_map.get(mid)
    G.history_map[mid] = entry
    if prev is None:
        G.history.append(entry)
    else:
        # Reemplaza en la lista visible
        for i, e in enumerate(G.history):
            if e.get("id","") == mid:
                G.history[i] = entry
                break

def _save_history_final(entry: dict):
    """Escribe SOLO partidas finalizadas (una línea por partida) al TXT."""
    header = "fecha_hora;j1;j2;g1;g2;f1;f2;i1;i2;resultado;match_id\n"
    line = f"{entry['ts']};{entry['j1']};{entry['j2']};{entry['g1']};{entry['g2']};{entry['f1']};{entry['f2']};{entry['i1']};{entry['i2']};{entry['resultado']};{entry.get('id','')}\n"
    try:
        need_header = not os.path.exists(HISTORY_FILE)
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            if need_header: f.write(header)
            f.write(line)
        app.log(f"[HIST] Final guardado en {os.path.basename(HISTORY_FILE)}") if app else print("[HIST] Guardado")
    except Exception as e:
        app.log(f"[HIST] Error guardando archivo: {e}") if app else print("[HIST]", e)

class TCPServer:
    def __init__(self, host, port, on_connect=None, on_disconnect=None, logger=print, ui=None):
        self.host=host; self.port=port
        self.on_connect=on_connect; self.on_disconnect=on_disconnect
        self.log=logger; self.ui=ui
        self.server_socket=None; self.alive=False; self.th=None

    def start(self):
        if self.alive: return
        self.alive = True
        self.th = threading.Thread(target=self._serve, daemon=True)
        self.th.start()
        self.log(f"[TCP] Servidor en {self.host}:{self.port}")

    def stop(self):
        self.alive=False
        try:
            if self.server_socket: self.server_socket.close()
        except: pass
        self.log("[TCP] Servidor detenido.")

    def _serve(self):
        addr=(self.host,self.port)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(addr); s.listen(1)
            self.server_socket = s
            self.log(f"[TCP] Escuchando en {self.host}:{self.port}")
        except OSError as e:
            self.log(f"[TCP] Error bind/listen: {e}")
            self.alive=False; return
        while self.alive:
            try:
                self.log("Esperando conexiones entrantes...")
                c, a = s.accept()
            except OSError:
                break
            self.log("Conexión aceptada")
            if self.on_connect: self.on_connect()
            try:
                self._handle(c, a)
            finally:
                try: c.close()
                except: pass
                self.log("[TCP] Socket cliente cerrado")
                if self.on_disconnect: self.on_disconnect()
        self.log("[TCP] Loop finalizado")

    def _handle(self, c: socket.socket, a):
        try: peer = c.getpeername()
        except: peer = a
        self.log(f"Conexion establecida desde {peer}")
        while self.alive:
            data = c.recv(1024)
            if not data:
                self.log(f"Cliente {peer} desconectado."); break
            for tok in _tokens_from_bytes(data):
                self.log(f"Mensaje recibido desde {peer}: {tok}")
                self._apply_token(tok)

    def _ensure_match_id(self):
        if not G.match_id: G.match_id = str(uuid.uuid4())

    def _snapshot_mem(self, estado="EN_CURSO"):
        """Actualiza SOLO la memoria (no escribe en archivo)."""
        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "j1": G.name[0], "j2": G.name[1],
            "g1": G.goals[0], "g2": G.goals[1],
            "f1": G.fallos[0], "f2": G.fallos[1],
            "i1": G.intentos[0], "i2": G.intentos[1],
            "resultado": estado, "id": G.match_id
        }
        _upsert_history_memory(entry)

    def _register_shot(self, failed: bool):
        if G.match_over(): return
        j = G.active
        if G.intentos[j] >= G.max_intentos:
            self.log(f"[INTENTOS] {G.name[j]} ya completó {G.max_intentos}/{G.max_intentos}")
            return
        G.intentos[j] += 1
        if failed and G.fallos[j] < G.max_intentos:
            G.fallos[j] += 1
            self.log(f"[FALLO] {G.name[j]} acumula {G.fallos[j]}/{G.max_intentos}")
        if app: 
            app.after(0, app.update_attempt_labels)
            app.after(0, app.refresh_score)
        self._snapshot_mem("EN_CURSO")
        if G.match_over(): self._finish_match()

    def _finish_match(self):
        if G.goals[0] > G.goals[1]: result = f"Ganó {G.name[0]}"
        elif G.goals[1] > G.goals[0]: result = f"Ganó {G.name[1]}"
        else: result = "Empate"
        self.log(f"[FIN] {result}. Marcador {G.goals[0]}–{G.goals[1]}.")

        entry = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "j1": G.name[0], "j2": G.name[1],
            "g1": G.goals[0], "g2": G.goals[1],
            "f1": G.fallos[0], "f2": G.fallos[1],
            "i1": G.intentos[0], "i2": G.intentos[1],
            "resultado": result, "id": G.match_id
        }
        _upsert_history_memory(entry)   # reemplaza el snapshot en memoria
        _save_history_final(entry)      # escribe SOLO ahora en el TXT

        if app: app.after(0, lambda: app.show_result_dialog(result))

    def _apply_token(self, tok: str):
        if tok.startswith("GK:"):
            bits = _parse_gk(tok)
            if bits is None:
                self.log("[TCP] GK inválido"); return
            G.gk_bits = bits
            self._ensure_match_id(); self._snapshot_mem("EN_CURSO")
            self.log(f"[GK] Porteros: {['1' if b else '0' for b in G.gk_bits]}"); return
        if tok == "H":
            G.first=0; G.active=0; G.reset_match()
            if app:
                app.after(0, app.update_attempt_labels)
                app.after(0, app.refresh_score)
            s_transition(); 
            if app: app.after(3000, s_whistle_go)
            self._snapshot_mem("EN_CURSO"); self.log("[JUEGO] Inicia J1 (por Raspi)"); return
        if tok == "I":
            G.first=1; G.active=1; G.reset_match()
            if app:
                app.after(0, app.update_attempt_labels)
                app.after(0, app.refresh_score)
            s_transition(); 
            if app: app.after(3000, s_whistle_go)
            self._snapshot_mem("EN_CURSO"); self.log("[JUEGO] Inicia J2 (por Raspi)"); return
        if tok == "G":
            G.active = 1 - G.active
            s_transition(); 
            if app: app.after(3000, s_whistle_go)
            self._ensure_match_id(); self._snapshot_mem("EN_CURSO")
            self.log(f"[JUEGO] Cambio, ahora activo: {G.name[G.active]}"); return
        if tok in PALETA_IDX:
            idx = PALETA_IDX[tok]
            if 0 <= idx < 6 and G.gk_bits[idx]:
                s_boo(); self.log(f"[ATAJADA] Paleta {tok} defendida")
                self._register_shot(failed=True)
            else:
                s_goal(); G.goals[G.active] += 1
                self.log(f"[GOL] {G.name[G.active]} anota (paleta {tok})")
                self._register_shot(failed=False)
            return

# ------------------ UI ------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CEFoot — Marcador")

        self.attributes("-fullscreen", True)
        self.bind("<F11>", lambda e: self.attributes("-fullscreen", not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        st = ttk.Style(self); st.theme_use("clam")
        st.configure("TFrame", background="#111")
        st.configure("TLabel", background="#111", foreground="#EEE")
        st.configure("Name.TLabel", font=("Segoe UI", 18, "bold"))
        st.configure("Score.TLabel", font=("Segoe UI", 64, "bold"))
        st.configure("Conn.TLabel", font=("Segoe UI", 10, "bold"))

        root = ttk.Frame(self, padding=18)
        root.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.96, relheight=0.96)

        self._child = None

        # Conexión + botones
        self.conn_panel = ttk.Frame(root); self.conn_panel.place(x=0, y=0)
        self.conn_label = ttk.Label(self.conn_panel, text="Desconectado",
                                    style="Conn.TLabel", foreground="#e05555")
        self.conn_label.grid(row=0, column=0, padx=6, pady=(2,1), sticky="w")

        btns_conn = ttk.Frame(self.conn_panel)
        btns_conn.grid(row=1, column=0, sticky="w", padx=6)
        ttk.Button(btns_conn, text="Nueva partida", command=self.new_match).grid(row=0, column=0, padx=(0,8))
        ttk.Button(btns_conn, text="Historial…", command=self.open_history).grid(row=0, column=1, padx=(0,8))
        ttk.Button(btns_conn, text="Acerca de…", command=self.open_about).grid(row=0, column=2)

        # Stats arriba-derecha
        self.stats_panel = ttk.Frame(root)
        self.stats_panel.place(relx=1.0, y=0, x=-10, anchor="ne")
        self.lbl_fallos = ttk.Label(self.stats_panel, text="", style="Conn.TLabel")
        self.lbl_rest   = ttk.Label(self.stats_panel, text="", style="Conn.TLabel")
        self.lbl_fallos.grid(row=0, column=0, sticky="e"); self.lbl_rest.grid(row=1, column=0, sticky="e")

        # Encabezado de escudos
        badgeRow = ttk.Frame(root); badgeRow.grid(row=0, column=0, columnspan=3, sticky="n", pady=(0,10))
        badgeRow.columnconfigure(0, weight=1); badgeRow.columnconfigure(1, weight=1)
        self.badgeL = ttk.Label(badgeRow); self.badgeL.grid(row=0, column=0, sticky="n", padx=20)
        self.badgeR = ttk.Label(badgeRow); self.badgeR.grid(row=0, column=1, sticky="n", padx=20)

        # Cuerpo 3 columnas
        root.rowconfigure(1, weight=6)
        for c in range(3): root.columnconfigure(c, weight=1)

        left = ttk.Frame(root); left.grid(row=1, column=0, sticky="n", padx=(0,10))
        self.nameL = ttk.Label(left, text=G.name[0], style="Name.TLabel"); self.nameL.pack(anchor="n")
        self.photoL = ttk.Label(left); self.photoL.pack(anchor="n", pady=(6,0))

        center = ttk.Frame(root); center.grid(row=1, column=1, sticky="n")
        self.score_var = tk.StringVar()
        self.score = ttk.Label(center, textvariable=self.score_var, style="Score.TLabel")
        self.score.pack(anchor="n", pady=(18,0))

        right = ttk.Frame(root); right.grid(row=1, column=2, sticky="n", padx=(10,0))
        self.nameR = ttk.Label(right, text=G.name[1], style="Name.TLabel"); self.nameR.pack(anchor="n")
        self.photoR = ttk.Label(right); self.photoR.pack(anchor="n", pady=(6,0))

        # Barra inferior
        bar = ttk.Frame(root); bar.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10,0))
        bar.columnconfigure(0, weight=1); bar.columnconfigure(1, weight=1)
        leftB = ttk.Frame(bar); leftB.grid(row=0,column=0,sticky="w")
        rightB= ttk.Frame(bar); rightB.grid(row=0,column=1,sticky="e")

        ttk.Button(leftB, text="Personalizar…", command=self.open_customize).grid(row=0,column=0,padx=(0,10))
        self.btn_ambient = ttk.Button(leftB, text="Ambiente: ON", command=self.toggle_ambient)
        self.btn_ambient.grid(row=0, column=1, padx=(0,10))
        ttk.Button(leftB, text="Moneda (cara/cruz)", command=self.open_coin_window).grid(row=0,column=2)

        ttk.Button(rightB, text="Elegir J1 (GP5-H)", command=lambda:self._hint_raspi("H")).grid(row=0,column=0,padx=(0,8))
        ttk.Button(rightB, text="Elegir J2 (GP5-I)", command=lambda:self._hint_raspi("I")).grid(row=0,column=1,padx=(0,8))

        # Log
        self.log_box = tk.Text(root, height=6, state="disabled", bg="#0E0E0E", fg="#9ad")
        self.log_box.grid(row=3, column=0, columnspan=3, sticky="nsew", pady=(10,0))
        root.rowconfigure(3, weight=1)

        self.refresh_all()

        # Ambiente
        if os.path.exists(os.path.join(BASE,"7_Ambiente.mp3")):
            S.ambient_start("7_Ambiente.mp3"); self.log("Ambiente ON (pygame)")
        else:
            self.btn_ambient.configure(text="Ambiente: OFF"); self.log("Ambiente no encontrado: 7_Ambiente.mp3")

        # Carga historial FINAL guardado en TXT (solo partidas terminadas)
        self._load_history_from_file()

        # TCP
        self.tcp = TCPServer(
            HOST, PORT,
            on_connect=lambda: self.after(0, lambda: self.set_connected(True) | s_connect()),
            on_disconnect=lambda: self.after(0, lambda: self.set_connected(False)),
            logger=self.log, ui=self
        )
        self.tcp.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # Helpers UI
    def refresh_all(self):
        self.photoL.configure(image=G.photo[0] if G.photo[0] else "", text="" if G.photo[0] else G.name[0][:1]); self.photoL.image = G.photo[0]
        self.photoR.configure(image=G.photo[1] if G.photo[1] else "", text="" if G.photo[1] else G.name[1][:1]); self.photoR.image = G.photo[1]
        self.badgeL.configure(image=G.badge[0] if G.badge[0] else "", text=""); self.badgeL.image = G.badge[0]
        self.badgeR.configure(image=G.badge[1] if G.badge[1] else "", text=""); self.badgeR.image = G.badge[1]
        self.nameL.configure(text=G.name[0]); self.nameR.configure(text=G.name[1])
        self.refresh_score(); self.update_attempt_labels()

    def refresh_score(self):
        self.score_var.set(f"{G.goals[0]} — {G.goals[1]}")

    def update_attempt_labels(self):
        lim = G.max_intentos
        j1_r = max(lim - G.intentos[0], 0)
        j2_r = max(lim - G.intentos[1], 0)
        self.lbl_fallos.configure(text=f"Fallidos  J1: {G.fallos[0]}/{lim}   |   J2: {G.fallos[1]}/{lim}")
        self.lbl_rest.configure(text=f"Restantes J1: {j1_r}         |   J2: {j2_r}")

    def set_connected(self, ok: bool):
        self.conn_label.configure(text=("Conectado" if ok else "Desconectado"),
                                  foreground=("#54d17a" if ok else "#e05555"))
        self.log("Conectado" if ok else "Desconectado")

    def log(self, msg):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", time.strftime("[%H:%M:%S] ")+msg+"\n")
        self.log_box.see("end"); self.log_box.configure(state="disabled")

    def _hint_raspi(self, which): self.log(f"[PISTA] Pulsa el botón en la Raspi para enviar '{which}'.")

    # Ventanas únicas
    def _open_singleton(self, builder, w, h, title):
        if self._child and self._child.winfo_exists():
            try: self._child.destroy()
            except: pass
        win = tk.Toplevel(self); self._child = win
        self._center_child(win, w, h); win.title(title)
        win.transient(self); win.grab_set()
        return win

    def show_result_dialog(self, result_text: str):
        win = self._open_singleton(lambda: None, 640, 360, "Resultado")
        frm = ttk.Frame(win, padding=18); frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=result_text, font=("Segoe UI", 36, "bold")).pack(pady=(10,6))
        ttk.Label(frm, text=f"{G.name[0]} {G.goals[0]} — {G.goals[1]} {G.name[1]}\n"
                            f"Fallos: {G.fallos[0]}/{G.max_intentos} vs {G.fallos[1]}/{G.max_intentos}",
                  font=("Segoe UI", 12)).pack(pady=(0,18))
        ttk.Button(frm, text="Cerrar", command=win.destroy).pack()

    def _rank_score(self, r):
        goles = r["g1"] + r["g2"]
        fallos = r["f1"] + r["f2"]
        bonus = 0.5 if r["resultado"] != "EN_CURSO" else 0.0
        return (goles, -fallos, bonus, r["ts"])

    def open_history(self):
        win = self._open_singleton(lambda: None, 1180, 640, "Historial de partidas")
        frm = ttk.Frame(win, padding=10); frm.pack(fill="both", expand=True)

        topbox = ttk.Labelframe(frm, text="Top 3 partidas"); topbox.pack(fill="x", pady=(0,10))
        top = sorted(G.history, key=self._rank_score, reverse=True)[:3]
        for i, r in enumerate(top, 1):
            ttk.Label(topbox, text=f"{i}. {r['j1']} {r['g1']}–{r['g2']} {r['j2']} | "
                                   f"Fallos: {r['f1']}/{G.max_intentos} vs {r['f2']}/{G.max_intentos} | "
                                   f"{r['resultado']} | {r['ts']}",
                      style="TLabel").pack(anchor="w", padx=8, pady=2)

        cols = ("ts","j1","j2","g1","g2","f1","f2","i1","i2","resultado","id")
        tree = ttk.Treeview(frm, columns=cols, show="headings", height=20)
        headers = {
            "ts":"Fecha/Hora", "j1":"Jugador 1", "j2":"Jugador 2",
            "g1":"Goles J1", "g2":"Goles J2", "f1":"Fallos J1", "f2":"Fallos J2",
            "i1":"Intentos J1", "i2":"Intentos J2", "resultado":"Estado/Resultado", "id":"Match ID"
        }
        widths = {"ts":170, "j1":200, "j2":200, "resultado":170, "id":260,
                  "g1":90, "g2":90, "f1":100, "f2":100, "i1":110, "i2":110}
        for c in cols:
            tree.heading(c, text=headers[c])
            tree.column(c, width=widths.get(c, 120), anchor="center", stretch=True)
        xscroll = ttk.Scrollbar(frm, orient="horizontal", command=tree.xview)
        yscroll = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
        tree.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y"); xscroll.pack(fill="x")

        for r in G.history:
            tree.insert("", "end", values=(r["ts"], r["j1"], r["j2"], r["g1"], r["g2"],
                                           r["f1"], r["f2"], r["i1"], r["i2"], r["resultado"], r.get("id","")))
        ttk.Frame(frm).pack(fill="x", pady=(8,0))
        ttk.Button(frm, text="Abrir archivo de historial", command=self._open_history_file).pack(anchor="e")

    def _open_history_file(self):
        if os.path.exists(HISTORY_FILE):
            try: os.startfile(HISTORY_FILE)
            except Exception: self.log(f"[HIST] Archivo en: {HISTORY_FILE}")
        else:
            self.log("[HIST] Aún no hay archivo de historial.")

    def open_coin_window(self):
        win = self._open_singleton(lambda: None, 500, 360, "Moneda")
        frm = ttk.Frame(win, padding=16); frm.pack(fill="both", expand=True)
        lbl = ttk.Label(frm, text="", font=("Segoe UI", 28, "bold")); lbl.pack(pady=(10,12))
        ttk.Label(frm, text="Animación aleatoria. El inicio real lo decide tu botón en la Raspi (H/I).",
                  font=("Segoe UI", 10)).pack(pady=(0,8))
        btn = ttk.Button(frm, text="Iniciar moneda"); btn.pack(pady=6)
        def start_flip():
            btn.state(["disabled"]); flips = 22
            def tick(i):
                if i>=flips:
                    lbl.configure(text=f"Resultado: {random.choice(['Cara','Cruz'])}"); return
                lbl.configure(text="Cara" if i%2==0 else "Cruz"); win.after(70, lambda: tick(i+1))
            tick(0)
        btn.configure(command=start_flip)

    def open_customize(self):
        win = self._open_singleton(lambda: None, 720, 520, "Personalizar")
        f = ttk.Frame(win, padding=12); f.pack(fill="both", expand=True)
        def pick_photo(idx):
            p = filedialog.askopenfilename(title="Elegir imagen (GIF/PNG/JPG)",
                                           filetypes=[("Imagen","*.gif;*.png;*.jpg;*.jpeg")])
            if not p: return
            G.ppath[idx]=p; G.photo[idx]=load_img(p); self.refresh_all()
        lf1 = ttk.Labelframe(f, text="Jugador 1"); lf1.grid(row=0,column=0,sticky="nsew",padx=(0,10))
        n1 = tk.StringVar(value=G.name[0])
        ttk.Label(lf1, text="Nombre:").grid(row=0,column=0,sticky="w"); ttk.Entry(lf1,textvariable=n1,width=22).grid(row=0,column=1,sticky="w",padx=6)
        ttk.Label(lf1, text="Equipo:").grid(row=1,column=0,sticky="w",pady=(6,0))
        cb1 = ttk.Combobox(lf1, state="readonly", values=[t[0] for t in G.teams], width=20); cb1.current(G.team_idx[0]); cb1.grid(row=1,column=1,sticky="w",padx=6,pady=(6,0))
        ttk.Button(lf1, text="Cambiar foto…", command=lambda:pick_photo(0)).grid(row=2,column=0,columnspan=2,pady=(8,0))
        lf2 = ttk.Labelframe(f, text="Jugador 2"); lf2.grid(row=0,column=1,sticky="nsew",padx=(10,0))
        n2 = tk.StringVar(value=G.name[1])
        ttk.Label(lf2, text="Nombre:").grid(row=0,column=0,sticky="w"); ttk.Entry(lf2,textvariable=n2,width=22).grid(row=0,column=1,sticky="w",padx=6)
        ttk.Label(lf2, text="Equipo:").grid(row=1,column=0,sticky="w",pady=(6,0))
        cb2 = ttk.Combobox(lf2, state="readonly", values=[t[0] for t in G.teams], width=20); cb2.current(G.team_idx[1]); cb2.grid(row=1,column=1,sticky="w",padx=6,pady=(6,0))
        ttk.Button(lf2, text="Cambiar foto…", command=lambda:pick_photo(1)).grid(row=2,column=0,columnspan=2,pady=(8,0))
        def apply_close():
            G.name[0]=n1.get().strip() or "Jugador 1"
            G.name[1]=n2.get().strip() or "Jugador 2"
            G.set_team(0, cb1.current()); G.set_team(1, cb2.current())
            self.refresh_all(); win.destroy()
        ttk.Button(f, text="Guardar", command=apply_close).grid(row=1,column=1,sticky="e",pady=(10,0))

    def open_about(self):
        win = self._open_singleton(lambda: None, 900, 680, "Acerca de los creadores")
        frm = ttk.Frame(win, padding=16); frm.pack(fill="both", expand=True)

        head = ttk.Frame(frm); head.pack(fill="x", pady=(0,10))
        ttk.Label(head, text="Año 2025", font=("Segoe UI", 18, "bold")).pack(anchor="center")
        ttk.Label(head, text="Profesor: Milton Villegas Lemus", font=("Segoe UI", 11)).pack(anchor="center", pady=(4,0))
        ttk.Label(head, text="Asistente: Asly Barahona", font=("Segoe UI", 11)).pack(anchor="center", pady=(2,0))
        ttk.Label(head, text="País de producción: Costa Rica", font=("Segoe UI", 11)).pack(anchor="center", pady=(2,0))
        ttk.Label(head, text="Versión: CEFoot Ver 4.1", font=("Segoe UI", 11, "bold")).pack(anchor="center", pady=(2,0))

        body = ttk.Frame(frm); body.pack(fill="both", expand=True, pady=(10,0))
        body.columnconfigure(0, weight=1); body.columnconfigure(1, weight=1)

        anth_img = cargar_img_cuadrada("Anthony", 256)
        luis_img  = cargar_img_cuadrada("Luis", 256)

        left = ttk.Frame(body, padding=8); left.grid(row=0, column=0, sticky="nsew")
        la = ttk.Label(left, image=anth_img); la.image = anth_img; la.pack(anchor="center", pady=(0,8))
        ttk.Label(left, text="Nombre: Anthony Fabricio Montiel López", font=("Segoe UI", 11, "bold")).pack(anchor="center")
        ttk.Label(left, text="Cédula: 2025132603", font=("Segoe UI", 11)).pack(anchor="center")
        ttk.Label(left, text="Carrera (CE): Ingeniería en Computadores", font=("Segoe UI", 11)).pack(anchor="center")
        ttk.Label(left, text="Asignatura: Fundamentos Computacionales", font=("Segoe UI", 11)).pack(anchor="center")

        right = ttk.Frame(body, padding=8); right.grid(row=0, column=1, sticky="nsew")
        lr = ttk.Label(right, image=luis_img); lr.image = luis_img; lr.pack(anchor="center", pady=(0,8))
        ttk.Label(right, text="Nombre: Luis Diego Murillo Matarrita", font=("Segoe UI", 11, "bold")).pack(anchor="center")
        ttk.Label(right, text="Cédula: 2025068058", font=("Segoe UI", 11)).pack(anchor="center")
        ttk.Label(right, text="Carrera (CE): Ingeniería en Computadores", font=("Segoe UI", 11)).pack(anchor="center")
        ttk.Label(right, text="Asignatura: Fundamentos Computacionales", font=("Segoe UI", 11)).pack(anchor="center")

        foot = ttk.Labelframe(frm, text="Uso recomendado"); foot.pack(fill="x", pady=(12,0))
        ttk.Label(foot, text="• Mantén la Raspi y el PC en la misma red y abre la app antes de conectar la Raspi.",
                  font=("Segoe UI", 10)).pack(anchor="w", padx=10, pady=(4,2))
        ttk.Label(foot, text="• Para reiniciar sin perder historial, usa ‘Nueva partida’; no cierres la ventana principal durante el juego.",
                  font=("Segoe UI", 10)).pack(anchor="w", padx=10, pady=(0,8))

    def toggle_ambient(self):
        if S.ambient_on:
            S.ambient_stop(); self.btn_ambient.configure(text="Ambiente: OFF"); self.log("Ambiente OFF")
        else:
            S.ambient_start("7_Ambiente.mp3"); self.btn_ambient.configure(text="Ambiente: ON"); self.log("Ambiente ON")

    def new_match(self):
        G.reset_match(); self.refresh_all(); self.log("[PARTIDA] Nueva partida lista.")

    def _center_child(self, win, w, h):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    def reload_images(self):
        for i, tag in enumerate(("Jugador1","Jugador2")):
            p = G.ppath[i]; self.log(f"[IMG] {tag} -> {p if p else 'NO ENCONTRADO'}")
            G.photo[i] = load_img(p) if p else None
        pL = G.teams[G.team_idx[0]][1] if G.teams and 0 <= G.team_idx[0] < len(G.teams) else ""
        pR = G.teams[G.team_idx[1]][1] if G.teams and 0 <= G.team_idx[1] < len(G.teams) else ""
        self.log(f"[IMG] Escudo J1 -> {pL if pL else 'NO ENCONTRADO'}")
        self.log(f"[IMG] Escudo J2 -> {pR if pR else 'NO ENCONTRADO'}")
        G.badge[0] = load_img(pL) if pL else None
        G.badge[1] = load_img(pR) if pR else None
        self.refresh_all()

    def _load_history_from_file(self):
        if not os.path.exists(HISTORY_FILE):
            self.log("[HIST] No hay archivo previo de historial."); return
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            if not lines: return
            start = 1 if lines[0].lower().startswith("fecha_hora;") else 0
            for ln in lines[start:]:
                parts = ln.split(";")
                if len(parts) < 11: continue
                ts, j1, j2, g1, g2, f1, f2, i1, i2, res, mid = parts[:11]
                entry = {
                    "ts": ts, "j1": j1, "j2": j2, "g1": int(g1), "g2": int(g2),
                    "f1": int(f1), "f2": int(f2), "i1": int(i1), "i2": int(i2),
                    "resultado": res, "id": mid
                }
                _upsert_history_memory(entry)
            self.log(f"[HIST] Cargadas {len(G.history)} partidas finalizadas.")
        except Exception as e:
            self.log(f"[HIST] Error leyendo historial: {e}")

    def _on_close(self):
        try:
            if hasattr(self, "tcp") and self.tcp: self.tcp.stop()
        except Exception as e:
            self.log(f"[TCP] Error al detener: {e}")
        try: S.ambient_stop()
        except: pass
        self.destroy()

# ------------------ Main ------------------
S = Sounder(BASE)
app=None
if __name__ == "__main__":
    app = App()
    for base in ("Jugador1","Jugador2","Escudo1","Escudo2","Escudo3"):
        cand = [os.path.join(BASE, base+ext) for ext in (".gif",".png",".jpg",".jpeg")]
        ok = any(os.path.exists(p) for p in cand)
        app.log(f" - {base}.* {'OK' if ok else 'NO ENCONTRADO'}")
        if ok:
            for p in cand:
                if os.path.exists(p): app.log(f"   -> {p}"); break
    app.reload_images()
    app.log("Listo: registro único por partida en TXT (solo al finalizar).")
    app.mainloop()
