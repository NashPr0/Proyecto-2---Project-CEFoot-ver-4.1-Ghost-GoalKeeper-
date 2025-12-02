import sys, time
from machine import Pin, ADC
import urandom   #  añadido para el bit de habilitación aleatorio

# ===== Config juego =====
SHIFTREG_ACTIVE_HIGH   = True
PALETA_PRESSED_IS_HIGH = True   # 1 = alimentada
UMBRAL_CAIDA_MS        = 100    # ≥0.1 s en 0 para contar intento
COOLDOWN_PRE_TURNO_S   = 3      # parpadeo previo (3 s)
BLINK_ON_MS            = 220
BLINK_OFF_MS           = 780
TOTAL_INTENTOS         = 10     # 5 por jugador
BTN_DB_MS              = 40
LONG_PRESS_MS          = 800

# Anti-ruido del pot
POT_SAMPLE_MS          = 40
POT_STABLE_COUNT       = 4
POT_PRINT_RATE_MS      = 400

# ===== Pines =====
PAL_GPIOS = [12,11,10,9,7,8]  # A..F (izq→der)
paletas = [Pin(g, Pin.IN, Pin.PULL_DOWN if PALETA_PRESSED_IS_HIGH else Pin.PULL_UP)
           for g in PAL_GPIOS]
BTN   = Pin(5,  Pin.IN, Pin.PULL_DOWN if PALETA_PRESSED_IS_HIGH else Pin.PULL_UP)
LED_J1= Pin(27, Pin.OUT)
LED_J2= Pin(22, Pin.OUT)
DATA  = Pin(18, Pin.OUT)
CLK   = Pin(19, Pin.OUT)
POT   = ADC(26)

# Pines hacia el circuito Decrementador 3:
# A (MSB) -> GP16
# B       -> GP14
# C (LSB) -> GP15
# EN      -> GP17
DEC_A  = Pin(16, Pin.OUT)  # A: bit más significativo
DEC_B  = Pin(14, Pin.OUT)  # B: bit intermedio
DEC_C  = Pin(15, Pin.OUT)  # C: bit menos significativo
DEC_EN = Pin(17, Pin.OUT)  # bit de habilitación

# ===== Estado de juego =====
jugador_activo = 0
goles = [0, 0]
intento_idx = 0
esperando_boton = True

gk_index = 0
gk_pattern = [False]*6

# ===== 74HC164 =====
def _clk(): CLK.value(1); CLK.value(0)
def _shift(bit:int):
    if not SHIFTREG_ACTIVE_HIGH: bit ^= 1
    DATA.value(bit); _clk()
def _clear_sr(n=8):
    off = 0 if SHIFTREG_ACTIVE_HIGH else 1
    DATA.value(off)
    for _ in range(n): _clk()
def marco_set_bits_qaqf(bits):
    _clear_sr(8)
    for b in reversed(bits): _shift(1 if b else 0)
def marco_all(on:bool): marco_set_bits_qaqf([1 if on else 0]*6)
def aplicar_leds_jugador():
    LED_J1.value(1 if jugador_activo==0 else 0)
    LED_J2.value(1 if jugador_activo==1 else 0)

# ======= Wi-Fi / TCP  =======
import network, usocket as socket, uselect as select

SSID    = "Anthony"             # editar si cambia
PASS    = "2025132688"         # editar si cambia
PC_HOST = "10.20.233.189"     # IP de PC (Wi-Fi)
PC_PORT = 8001

server_address = (PC_HOST, PC_PORT)

_sock = None
_poll = None
_net_buf = b""


def connectToWifi(timeout_ms=15000):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if wlan.isconnected():
        print("WiFi ya conectado:", wlan.ifconfig()); return True
    print("Conectando WiFi a:", SSID)
    wlan.connect(SSID, PASS)
    t0 = time.ticks_ms()
    while (not wlan.isconnected()) and time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
        time.sleep_ms(200)
    if wlan.isconnected():
        print("WiFi OK:", wlan.ifconfig()); return True
    print("WiFi TIMEOUT"); return False


def connectToPC():
    """Conecta y devuelve socket NO bloqueante (o None si falla)."""
    global _sock, _poll
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        print("socket creado")
        s.settimeout(5)
        s.connect(server_address)
        print("conexion exitosa")
        s.setblocking(False)
        p = select.poll(); p.register(s, select.POLLIN)
        _sock, _poll = s, p
        # saludo inicial
        s.sendall(b"Hola, este mensaje es enviado desde la raspy :)\n")
        return s
    except Exception as e:
        print("Error de conexion:", e)
        try:
            s.close()
        except:
            pass
        _sock, _poll = None, None
        return None


def net_poll(sock):
    """Lee tokens del servidor si los hay, sin bloquear."""
    global _net_buf, _sock, _poll
    if not sock or not _poll: return
    try:
        events = _poll.poll(0)
        if not events: return
        data = sock.recv(256)
        if not data:
            print("Servidor cerro la conexion.")
            try: sock.close()
            except: pass
            _sock, _poll = None, None
            return
        _net_buf += data
        text = _net_buf.decode('utf-8', 'ignore')
        tokens, tmp = [], ""
        for ch in text:
            if ch in "\r\n \t":
                if tmp: tokens.append(tmp); tmp = ""
            else:
                tmp += ch
        _net_buf = tmp.encode()
        for t in tokens:
            handle_pc_cmd(t.strip().upper())
    except Exception:
        # no romper el juego
        pass


def handle_pc_cmd(tok: str):
    # H/I: LEDs de jugador
    if tok == "H":
        LED_J1.value(1); LED_J2.value(0)
    elif tok == "I":
        LED_J1.value(0); LED_J2.value(1)
    # J..O: encender una línea del marco 3 s
    elif tok in ("J","K","L","M","N","O"):
        idx = ord(tok) - ord('J')
        bits = [0]*6; bits[idx] = 1
        marco_set_bits_qaqf(bits)
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < 3000:
            net_poll(_sock); time.sleep_ms(5)
        marco_all(False)
        
    elif tok.startswith("DEC:"):
        try:
            # formato esperado: DEC:<n>
            parts = tok.split(":")
            if len(parts) >= 2:
                n_val = int(parts[1])
                procesar_dec_desde_pc(n_val)
        except Exception as e:
            print("DEC cmd invalido:", tok, e)
    # otros tokens: ignorar


def send_tok(tok: str):
    """Envía 'tok\\n' si hay socket; no revienta si se corta."""
    if not _sock: return
    try:
        _sock.send((tok + "\n").encode())
    except Exception as e:
        print("send err:", repr(e))

# ===== Utilidades consola =====
PALETTE_CODES = ['A','B','C','D','E','F']
def _lista_porteros(bits):
    activos = [PALETTE_CODES[i] for i,b in enumerate(bits) if b]
    inact   = [PALETTE_CODES[i] for i,b in enumerate(bits) if not b]
    return activos, inact
def imprimir_porteros(bits):
    activos, inact = _lista_porteros(bits)
    print("PORTEROS ACTIVOS: {}  |  SIN PORTERO: {}".format(
        ",".join(activos) if activos else "(ninguno)",
        ",".join(inact)   if inact   else "(ninguno)"
    ))
    send_tok("GK:" + "".join('1' if b else '0' for b in bits))

# ===== 18 combinaciones (3 de 6) =====
def _gen_20():
    L=[]
    for i in range(6):
        for j in range(i+1,6):
            for k in range(j+1,6):
                bits=[0]*6
                bits[i]=bits[j]=bits[k]=1
                L.append(bits)
    return L
PATTERNS_18 = _gen_20()[:18]
def patron_por_indice(idx:int):
    idx = max(0, min(17, idx))
    return PATTERNS_18[idx][:]

# ===== Pot con filtro + publicación a PC =====
_pot_last_sample_ms = 0
_pot_raw_band       = -1
_pot_same_count     = 0
_pot_last_print_ms  = 0
_last_adc_hex       = None
_last_adc_t         = 0
ADC_PUB_EVERY_MS    = 250

def _map_raw_to_band(raw): return (raw * 18) // 65536

def _maybe_publish_adc():
    global _last_adc_hex, _last_adc_t
    now = time.ticks_ms()
    if time.ticks_diff(now, _last_adc_t) < ADC_PUB_EVERY_MS:
        return
    nib = (POT.read_u16() * 16) // 65536
    hx = "{:02X}".format(nib)
    if hx != _last_adc_hex:
        _last_adc_hex = hx
        send_tok(hx)
    _last_adc_t = now

def actualizar_porteros_desde_pot():
    global _pot_last_sample_ms, _pot_raw_band, _pot_same_count
    global gk_index, gk_pattern, _pot_last_print_ms

    now = time.ticks_ms()
    if time.ticks_diff(now, _pot_last_sample_ms) < POT_SAMPLE_MS:
        return
    _pot_last_sample_ms = now

    raw = POT.read_u16()
    band = _map_raw_to_band(raw)

    if band != _pot_raw_band:
        _pot_raw_band   = band
        _pot_same_count = 1
        return
    else:
        _pot_same_count += 1

    if _pot_same_count >= POT_STABLE_COUNT and band != gk_index:
        gk_index   = band
        gk_pattern = patron_por_indice(gk_index)
        if time.ticks_diff(now, _pot_last_print_ms) >= POT_PRINT_RATE_MS:
            imprimir_porteros(gk_pattern)
            _pot_last_print_ms = now

# ===== Lectura de paletas =====
def leer_paletas_raw():
    vals=[]
    for p in paletas:
        v = p.value()
        if PALETA_PRESSED_IS_HIGH:
            vals.append(1 if v==1 else 0)  # 1=alimentada
        else:
            vals.append(1 if v==0 else 0)
    return vals

def esperar_primer_caida_sostenida(umbral_ms=UMBRAL_CAIDA_MS):
    """Devuelve índice 0..5 de la PRIMERA paleta con 1->0 y 0 ≥ umbral_ms."""
    last = leer_paletas_raw()
    while True:
        actualizar_porteros_desde_pot()
        _maybe_publish_adc()
        net_poll(_sock)
        cur = leer_paletas_raw()
        for i in range(6):
            if last[i]==1 and cur[i]==0:
                t0 = time.ticks_ms()
                sostenida = True
                while time.ticks_diff(time.ticks_ms(), t0) < umbral_ms:
                    ci = leer_paletas_raw()[i]
                    if ci == 1:
                        sostenida = False
                        break
                    actualizar_porteros_desde_pot()
                    _maybe_publish_adc()
                    net_poll(_sock)
                    time.sleep_ms(1)
                if sostenida:
                    return i
        last = cur
        time.sleep_ms(2)

# ===== Botón / pre-turno =====
btn_ultimo = 0
btn_last_t = 0

def blink_pre_turno_3s():
    for _ in range(COOLDOWN_PRE_TURNO_S):
        marco_all(True)
        t_on = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t_on) < BLINK_ON_MS:
            actualizar_porteros_desde_pot(); _maybe_publish_adc(); net_poll(_sock); time.sleep_ms(5)
        marco_all(False)
        t_off = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t_off) < BLINK_OFF_MS:
            actualizar_porteros_desde_pot(); _maybe_publish_adc(); net_poll(_sock); time.sleep_ms(5)
    marco_all(False)

def esperar_boton_para_siguiente():
    global btn_ultimo, btn_last_t
    while True:
        v = BTN.value()
        now = time.ticks_ms()
        if v != btn_ultimo and time.ticks_diff(now, btn_last_t) > BTN_DB_MS:
            btn_last_t = now
            if v == (1 if PALETA_PRESSED_IS_HIGH else 0):
                send_tok("G")    # botón a la PC
                return
            btn_ultimo = v
        actualizar_porteros_desde_pot(); _maybe_publish_adc(); net_poll(_sock)
        time.sleep_ms(30)

# ===== Selección inicial =====
def _leer_char_consola(timeout_ms=8000):
    try:
        import uselect as select
        poll = select.poll()
        poll.register(sys.stdin, select.POLLIN)
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            res = poll.poll(100)
            if res:
                line = sys.stdin.readline()
                if not line: continue
                c = line.strip()
                if c == '1': return 0
                if c == '2': return 1
                print("Ingrese '1' o '2'.")
        return None
    except Exception:
        return None

def elegir_jugador_inicial():
    print("Aqui presentamo nuestro Futbol")
    print("Seleccione jugador inicial en consola (1 o 2) y presione Enter.")
    c = _leer_char_consola()
    if c is not None: return c
    print("Modo selección por botón: toque alterna J1/J2, mantenga (≥0.8 s) para confirmar.")
    sel = 0
    last_v = BTN.value()
    last_t = time.ticks_ms()
    while True:
        LED_J1.value(1 if sel==0 else 0)
        LED_J2.value(1 if sel==1 else 0)
        v = BTN.value()
        now = time.ticks_ms()
        if v != last_v and time.ticks_diff(now, last_t) > BTN_DB_MS:
            if v == (1 if PALETA_PRESSED_IS_HIGH else 0):
                t_press = time.ticks_ms()
                while BTN.value() == (1 if PALETA_PRESSED_IS_HIGH else 0):
                    net_poll(_sock); time.sleep_ms(5)
                dur = time.ticks_diff(time.ticks_ms(), t_press)
                if dur >= LONG_PRESS_MS:
                    return sel
                else:
                    sel ^= 1
            last_v = v
            last_t = now
        net_poll(_sock)
        time.sleep_ms(10)

# ===== Lógica Decrementador 3  =====
def escribir_entradas_dec3(bits3:int, habil:int):
    """
    Envía a las GP16, GP14 y GP15 las entradas A, B, C del circuito
    Decremento 3, y a GP17 el bit de habilitación EN.

    bits3: valor 0..7 (3 bits) en el orden A B C (A=MSB, C=LSB).
    habil: 0 o 1.
    """
    bits3 &= 0b111

    # C = bit 0 (LSB)
    DEC_C.value(bits3 & 0b001)
    # B = bit 1
    DEC_B.value((bits3 >> 1) & 0b001)
    # A = bit 2 (MSB)
    DEC_A.value((bits3 >> 2) & 0b001)
    # EN
    DEC_EN.value(1 if habil else 0)
    
def procesar_dec_desde_pc(n_original: int):
    """
    Comando remoto desde la Interfaz (PC):
    """
    if n_original < 0:
        n_original = 0

    # Valor que ve el circuito (3 bits)
    bits_in = n_original & 0b111
    en = 1  # en el modo "botón decrementar" siempre resta

    # Mandar entradas al circuito lógico (A,B,C,EN)
    escribir_entradas_dec3(bits_in, en)

    # Cálculo lógico equivalente a la salida del circuito (IN - 3, mod 8)
    bits_out = (bits_in - 0b011) & 0b111

    # Armar token para la Interfaz
    msg = "DECRES:{}:{:03b}:{:03b}:{}".format(
        n_original,  # valor cargado desde el label en PC
        bits_in,     # entradas A B C
        bits_out,    # resultado OUT del circuito
        bits_out     # resultado en decimal (0..7)
    )

    print("[DEC3-REMOTE]", msg)
    send_tok(msg)


def aplicar_decrementador3_solo_hw(jugador_idx:int):
    """
    Añade el gol al jugador  y luego:
      - Toma los 3 bits menos significativos del marcador de ese jugador.
      - Genera un bit EN aleatorio.
      - Envía A,B,C y EN al circuito decrementador.
      - Calcula la salida (IN-3) SOLO para imprimir / mandar a PC.
    NO modifica goles[jugador_idx] más allá del +1 normal.
    """
    global goles

    # 1) Sumar el gol como en el juego original
    goles[jugador_idx] += 1

    # 2) Copia en 3 bits para el circuito
    bits_in = goles[jugador_idx] & 0b111

    # 3) Bit de habilitación aleatorio
    en = urandom.getrandbits(1) & 0x1

    # 4) Mandar al hardware
    escribir_entradas_dec3(bits_in, en)

    # 5) Solo para demostración / no se usa para cambiar goles
    if en == 0:
        print("[DEC3] EN=0  IN={:03b}  (goles reales J{} = {})".format(
            bits_in, jugador_idx+1, goles[jugador_idx]))

    else:
        bits_out = (bits_in - 0b011) & 0b111
        print("[DEC3] EN=1  IN={:03b}  OUT={:03b}  (goles reales J{} = {})".format(
            bits_in, bits_out, jugador_idx+1, goles[jugador_idx]))

# ===== Anuncio y final =====
def anunciar_intento(n_actual, jugador):
    print("Intento {}/{} — Turno J{}".format(n_actual, TOTAL_INTENTOS, jugador+1))

def anunciar_resultado_y_salir():
    if   goles[0] > goles[1]:
        print("FIN DE PARTIDA — Ganador: J1  |  Marcador final: J1={}  J2={}".format(goles[0], goles[1]))
    elif goles[1] > goles[0]:
        print("FIN DE PARTIDA — Ganador: J2  |  Marcador final: J1={}  J2={}".format(goles[0], goles[1]))
    else:
        print("FIN DE PARTIDA — Empate  |  Marcador final: J1={}  J2={}".format(goles[0], goles[1]))
    print("¡Gracias por jugar!")

# ===== Bucle principal =====
def main():
    global jugador_activo, intento_idx, esperando_boton, gk_index, gk_pattern

    # RED
    connectToWifi()
    connectToPC()

    _clear_sr(8)
    marco_all(False)

    # Inicializar porteros y enviar a PC
    for _ in range(POT_STABLE_COUNT + 1):
        actualizar_porteros_desde_pot()
        time.sleep_ms(POT_SAMPLE_MS)
    imprimir_porteros(gk_pattern)

    # Selección inicial
    jugador_activo = elegir_jugador_inicial()
    aplicar_leds_jugador()
    anunciar_intento(0, jugador_activo)

    # Pre-turno inicial y arranca
    blink_pre_turno_3s()
    esperando_boton = False

    while True:
        net_poll(_sock)

        if intento_idx >= TOTAL_INTENTOS:
            anunciar_resultado_y_salir()
            marco_all(False)
            while True:
                net_poll(_sock); time.sleep_ms(200)

        if esperando_boton:
            esperar_boton_para_siguiente()
            jugador_activo ^= 1
            aplicar_leds_jugador()
            blink_pre_turno_3s()
            esperando_boton = False
            anunciar_intento(intento_idx + 1, jugador_activo)
            continue

        if intento_idx == 0:
            anunciar_intento(1, jugador_activo)

        # Intento activo: primera caída sostenida
        idx = esperar_primer_caida_sostenida()
        send_tok(PALETTE_CODES[idx])  # reportar paleta

        if gk_pattern[idx]:
            print("ATAJADA J{}  |  Marcador: J1={}  J2={}".format(
                jugador_activo+1, goles[0], goles[1]))
        else:
            # el gol se suma dentro de aplicar_decrementador3_solo_hw
            aplicar_decrementador3_solo_hw(jugador_activo)
            print("GOL J{}  |  Marcador: J1={}  J2={}".format(
                jugador_activo+1, goles[0], goles[1]))

        intento_idx += 1
        esperando_boton = True
        marco_all(False)

if __name__ == "__main__":
    main()
