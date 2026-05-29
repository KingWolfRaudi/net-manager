#!/usr/bin/env python3
"""
Módulo Aislado de Pruebas para Hotspot (AP) y NAT
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
        pass # Ignoramos errores menores en este entorno de pruebas

def get_internet_interface():
    """Intenta detectar qué interfaz tiene la ruta por defecto a Internet"""
    try:
        salida = subprocess.check_output("ip route | grep default", shell=True, text=True)
        return salida.split()[4]
    except:
        return None

def start_ap():
    internet_iface = get_internet_interface()
    print(f"\n🔥 Iniciando AP en [{AP_INTERFACE}]...")
    
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
        print(f"         > Internet detectado en [{internet_iface}]. Compartiendo conexión...")
        run(f"iptables -t nat -A POSTROUTING -o {internet_iface} -j MASQUERADE")
    else:
        print("         > No se detectó salida a Internet. El AP será solo local.")

    # 3. Escribir configuraciones
    print("   [3/5] Generando archivos hostapd y dnsmasq...")
    with open("/etc/ap_hostapd.conf", 'w') as f:
        f.write(f"interface={AP_INTERFACE}\ndriver=nl80211\nssid={AP_SSID}\nhw_mode=g\nchannel=6\nwpa=2\nwpa_passphrase={AP_PASS}\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n")
    
    with open("/etc/ap_dnsmasq.conf", 'w') as f:
        f.write(f"interface={AP_INTERFACE}\nbind-dynamic\ndhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,12h\ndhcp-option=3,192.168.4.1\ndhcp-option=6,8.8.8.8,8.8.4.4\n")

    # 4. Configurar red
    print("   [4/5] Levantando interfaz de red...")
    run(f"ip link set {AP_INTERFACE} down")
    run(f"ip addr flush dev {AP_INTERFACE}")
    run(f"ip addr add 192.168.4.1/24 dev {AP_INTERFACE}")
    run(f"ip link set {AP_INTERFACE} up")
    run("rfkill unblock wifi")

    # 5. Lanzar demonios
    print("   [5/5] Iniciando hostapd y dnsmasq...")
    subprocess.Popen(['hostapd', '-B', '/etc/ap_hostapd.conf'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    subprocess.Popen(['dnsmasq', '-C', '/etc/ap_dnsmasq.conf'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    print("\n✅ HOTSPOT ACTIVADO.")

def stop_ap():
    print(f"\n🔌 Deteniendo AP y restaurando sistema...")
    
    # 1. Limpiar procesos y reglas
    print("   [1/4] Matando procesos y limpiando iptables...")
    run("iptables -t nat -F")
    run("pkill -f 'hostapd -B /etc/ap_hostapd.conf'")
    run("pkill -f 'dnsmasq -C /etc/ap_dnsmasq.conf'")
    
    # 2. Limpiar interfaz
    print(f"   [2/4] Restaurando tarjeta [{AP_INTERFACE}]...")
    run(f"ip addr flush dev {AP_INTERFACE}")
    run(f"ip link set {AP_INTERFACE} down")
    run(f"ip link set {AP_INTERFACE} up")
    
    # 3. Revivir servicios
    print("   [3/4] Reiniciando systemd-resolved y wpa_supplicant...")
    run("systemctl start systemd-resolved")
    run("systemctl restart wpa_supplicant")
    
    # 4. Reconectar Netplan
    print("   [4/4] Aplicando configuración de Netplan...")
    run("netplan apply")
    
    print("\n✅ MODO CLIENTE RESTAURADO.")

def main():
    while True:
        print("\n" + "="*40)
        print("🛠️  LABORATORIO DE AP AISLADO")
        print("="*40)
        print("1. 🟢 Encender Hotspot")
        print("2. 🔴 Apagar Hotspot (Restaurar Internet)")
        print("0. Salir")
        print("="*40)
        
        opcion = input("Selecciona: ").strip()
        
        if opcion == '1':
            start_ap()
        elif opcion == '2':
            stop_ap()
        elif opcion == '0':
            break
        else:
            print("Opción inválida.")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("🔒 Ejecuta con sudo: sudo python3 ap_test.py")
        sys.exit(1)
    main()