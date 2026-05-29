#!/usr/bin/env python3
"""
Módulo Aislado de Pruebas para Hotspot (AP) y NAT
Incluye Modo Debug en Tiempo Real
"""

import subprocess
import os
import sys
import time

# --- CONFIGURACIÓN RÁPIDA ---
AP_INTERFACE = "wlp1s0"          # Tarjeta que emitirá el WiFi
AP_SSID = "Servidor_Mantenimiento"
AP_PASS = "acceso_local_123"

def run(command):
    """Ejecuta comandos del sistema y silencia la salida estándar"""
    try:
        subprocess.run(command, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        pass

def get_internet_interface():
    """Intenta detectar qué interfaz tiene la ruta por defecto a Internet"""
    try:
        salida = subprocess.check_output("ip route | grep default", shell=True, text=True)
        return salida.split()[4]
    except:
        return None

def start_ap(debug=False):
    internet_iface = get_internet_interface()
    modo = "DEBUG" if debug else "NORMAL"
    print(f"\n🔥 Iniciando AP en [{AP_INTERFACE}] (Modo {modo})...")
    
    # 1. Dormir servicios del cliente
    print("   [1/5] Deteniendo systemd-resolved y wpa_supplicant...")
    run("systemctl stop systemd-resolved")
    run("systemctl stop wpa_supplicant")
    run("pkill wpa_supplicant")

    # 2. Enrutamiento y NAT
    print("   [2/5] Configurando IP Forwarding y NAT...")
    run("sysctl -w net.ipv4.ip_forward=1")
    run("iptables -t nat -F")
    if internet_iface:
        run(f"iptables -t nat -A POSTROUTING -o {internet_iface} -j MASQUERADE")

    # 3. Escribir configuraciones
    print("   [3/5] Generando archivos hostapd y dnsmasq...")
    with open("/etc/ap_hostapd.conf", 'w') as f:
        f.write(f"interface={AP_INTERFACE}\ndriver=nl80211\nssid={AP_SSID}\nhw_mode=g\nchannel=6\nwpa=2\nwpa_passphrase={AP_PASS}\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n")
    
    with open("/etc/ap_dnsmasq.conf", 'w') as f:
        f.write(f"interface={AP_INTERFACE}\nbind-dynamic\ndhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,12h\ndhcp-option=3,192.168.4.1\ndhcp-option=6,8.8.8.8,8.8.4.4\n")
        if debug:
            f.write("log-dhcp\nlog-queries\n") # Activa logs detallados para el modo debug

    # 4. Lanzar hostapd PRIMERO
    print("   [4/5] Iniciando hostapd (Emisor WiFi)...")
    if debug:
        subprocess.Popen(['hostapd', '-B', '/etc/ap_hostapd.conf'])
    else:
        subprocess.Popen(['hostapd', '-B', '/etc/ap_hostapd.conf'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    time.sleep(3) # Damos 3 segundos para que hostapd se asiente

    # 5. Configurar red y Lanzar dnsmasq DESPUÉS
    print("   [5/5] Asignando IP y levantando dnsmasq...")
    run(f"ip addr flush dev {AP_INTERFACE}")
    run(f"ip addr add 192.168.4.1/24 dev {AP_INTERFACE}")
    run(f"ip link set {AP_INTERFACE} up")
    
    if debug:
        subprocess.Popen(['dnsmasq', '-C', '/etc/ap_dnsmasq.conf'])
        
        print("\n" + "="*50)
        print("🐛 MODO DEBUG ACTIVO - ESPERANDO CONEXIONES")
        print("Presiona Ctrl+C para salir de los logs")
        print("="*50 + "\n")
        try:
            os.system("tail -n 0 -f /var/log/syslog | grep --line-buffered -E 'hostapd|dnsmasq'")
        except KeyboardInterrupt:
            print("\n\n⏸️  Logs interrumpidos por el usuario.")
    else:
        subprocess.Popen(['dnsmasq', '-C', '/etc/ap_dnsmasq.conf'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("\n✅ HOTSPOT ACTIVADO.")

def stop_ap():
    print(f"\n🔌 Deteniendo AP y restaurando sistema...")
    
    print("   [1/4] Matando procesos y limpiando iptables...")
    run("iptables -t nat -F")
    run("pkill -f 'hostapd -B /etc/ap_hostapd.conf'")
    run("pkill -f 'dnsmasq -C /etc/ap_dnsmasq.conf'")
    run("pkill hostapd") # Fuerza bruta adicional
    run("pkill dnsmasq")
    
    print(f"   [2/4] Restaurando tarjeta [{AP_INTERFACE}]...")
    run(f"ip addr flush dev {AP_INTERFACE}")
    run(f"ip link set {AP_INTERFACE} down")
    run(f"ip link set {AP_INTERFACE} up")
    
    print("   [3/4] Reiniciando systemd-resolved y wpa_supplicant...")
    run("systemctl start systemd-resolved")
    run("systemctl restart wpa_supplicant")
    
    print("   [4/4] Aplicando configuración de Netplan...")
    run("netplan apply")
    
    print("\n✅ MODO CLIENTE RESTAURADO.")

def main():
    while True:
        print("\n" + "="*45)
        print("🛠️  LABORATORIO DE AP AISLADO (v2 Debug)")
        print("="*45)
        print("1. 🟢 Encender Hotspot (Silencioso)")
        print("2. 🔴 Apagar Hotspot (Restaurar Internet)")
        print("3. 🐛 Encender Hotspot (MODO DEBUG)")
        print("0. Salir")
        print("="*45)
        
        opcion = input("Selecciona: ").strip()
        
        if opcion == '1':
            start_ap(debug=False)
        elif opcion == '2':
            stop_ap()
        elif opcion == '3':
            start_ap(debug=True)
        elif opcion == '0':
            break
        else:
            print("Opción inválida.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("🔒 Ejecuta con sudo: sudo python3 ap_test.py")
        sys.exit(1)
    main()