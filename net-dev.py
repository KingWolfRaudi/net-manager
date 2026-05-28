#!/usr/bin/env python3
"""
Gestor de Redes WiFi y Hotspot para Ubuntu Server
Optimizado con selección dinámica de interfaces y AP configurable
"""

import subprocess
import os
import sys
import time
import yaml
import shutil
import ipaddress
from pathlib import Path

class NetplanWiFiManager:
    def __init__(self):
        self.netplan_dir = Path('/etc/netplan')
        self.backup_dir = Path('/etc/netplan/backups')
        self.backup_dir.mkdir(exist_ok=True)
        self.wifi_config_file = self.netplan_dir / '99-wifi-config.yaml'
        
        # Credenciales del AP por defecto
        self.ap_ssid = "Servidor_Mantenimiento"
        self.ap_password = "acceso_local_123"
        
        # Estado de interfaces
        self.client_interface = self.get_internal_interface()
        self.ap_interface = None # Se define dinámicamente al iniciar el AP
        
    def run_command(self, command, sudo=False, show_errors=False):
        try:
            if sudo:
                command = ['sudo'] + command
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if show_errors:
                print(f"\n⚠️  [DEBUG DEL SISTEMA] Detalle del error:")
                print(f"Comando: {' '.join(command)}")
                print(f"Error: {e.stderr.strip() if e.stderr else 'Sin salida de error'}\n")
            return None

    def get_all_wireless_interfaces(self):
        """Obtiene todas las interfaces inalámbricas del sistema"""
        interfaces = []
        try:
            result = subprocess.run(['ip', '-br', 'link', 'show'], capture_output=True, text=True)
            if result.stdout:
                for line in result.stdout.split('\n'):
                    parts = line.split()
                    if parts:
                        iface = parts[0]
                        if iface.startswith('wl'): # Atrapa wlan, wlp, wlx
                            interfaces.append(iface)
        except:
            pass
        return interfaces
        
    def get_internal_interface(self):
        """Identifica la tarjeta interna de la Chromebook (wlp o wlan)"""
        all_ifaces = self.get_all_wireless_interfaces()
        internals = [i for i in all_ifaces if not i.startswith('wlx')]
        return internals[0] if internals else 'wlp1s0'
    
    def backup_netplan_config(self):
        if self.wifi_config_file.exists():
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            backup_file = self.backup_dir / f"99-wifi-config_{timestamp}.yaml"
            shutil.copy2(self.wifi_config_file, backup_file)
    
    def scan_wifi_networks(self):
        print(f"📡 Preparando tarjeta {self.client_interface} y escaneando...")
        self.run_command(['ip', 'link', 'set', self.client_interface, 'up'], sudo=True)
        
        scan_result = None
        for intento in range(3):
            time.sleep(3)
            scan_result = self.run_command(['iw', 'dev', self.client_interface, 'scan'], sudo=True)
            if scan_result: break
            else: print(f"⏳ Inicializando hardware... (Intento {intento + 1}/3)")
        
        if not scan_result:
            print("❌ Error: La interfaz sigue ocupada.")
            return []

        networks, seen_ssids, unique_networks = {}, set(), []
        current_bss = None
        
        for line in scan_result.split('\n'):
            line = line.strip()
            if line.startswith('BSS '):
                current_bss = line.split()[1].split('(')[0]
                networks[current_bss] = {'essid': 'Oculta', 'encryption': 'Abierta', 'signal': ''}
            elif current_bss:
                if line.startswith('SSID:'):
                    essid = line.split('SSID:')[1].strip()
                    if essid and not essid.startswith('\\x00'): networks[current_bss]['essid'] = essid
                elif line.startswith('RSN:') or line.startswith('WPA:'):
                    networks[current_bss]['encryption'] = 'Protegida'
                elif line.startswith('signal:'):
                    networks[current_bss]['signal'] = line.split('signal:')[1].strip()
        
        for data in networks.values():
            if data['essid'] not in seen_ssids and data['essid'] != 'Oculta':
                unique_networks.append(data)
                seen_ssids.add(data['essid'])
        
        return sorted(unique_networks, key=lambda x: x['essid'])
    
    def connect_to_wifi(self, ssid, password=None, dhcp=True, static_ip=None):
        print(f"🔗 Configurando conexión a '{ssid}' en {self.client_interface}...")
        try:
            self.run_command(['ip', 'link', 'set', self.client_interface, 'up'], sudo=True)
            time.sleep(2)
            self.backup_netplan_config()
            
            wifi_config = {
                'network': {
                    'version': 2,
                    'wifis': {
                        self.client_interface: {
                            'access-points': {ssid: {} if not password else {'password': password}},
                            'dhcp4': dhcp
                        }
                    }
                }
            }
            
            if static_ip and not dhcp:
                interface_config = wifi_config['network']['wifis'][self.client_interface]
                interface_config['addresses'] = [static_ip['address']]
                if 'gateway' in static_ip:
                    interface_config['routes'] = [{'to': 'default', 'via': static_ip['gateway']}]
                if 'dns' in static_ip:
                    interface_config['nameservers'] = {'addresses': static_ip['dns']}
            
            with open(self.wifi_config_file, 'w') as f:
                yaml.dump(wifi_config, f, default_flow_style=False)
            os.chmod(self.wifi_config_file, 0o600)
            
            return self.apply_netplan_config()
        except Exception as e:
            print(f"❌ Error configurando WiFi: {e}")
            return False
    
    def apply_netplan_config(self):
        try:
            print("🔄 Generando y aplicando configuración netplan...")
            if self.run_command(['netplan', 'generate'], sudo=True, show_errors=True) is None: return False
            if self.run_command(['netplan', 'apply'], sudo=True, show_errors=True) is None: return False
            
            print("⏳ Esperando que la conexión se establezca (10s)...")
            time.sleep(10)
            return self.check_connection()
        except Exception as e:
            print(f"❌ Error aplicando netplan: {e}")
            return False
    
    def check_connection(self):
        interface_status = self.run_command(['ip', 'addr', 'show', self.client_interface])
        has_ip = False
        if interface_status and 'inet ' in interface_status:
            for line in interface_status.split('\n'):
                if 'inet ' in line:
                    print(f"✅ Dirección IP asignada: {line.split()[1]}")
                    has_ip = True
                    break
        if not has_ip:
            print("❌ Sin IP asignada. Revisa la contraseña o el router.")
            return False
        try:
            subprocess.run(['ping', '-c', '3', '-W', '5', '8.8.8.8'], capture_output=True, check=True)
            print("✅ Conexión a Internet activa")
            return True
        except subprocess.CalledProcessError:
            print("⚠️  Sin respuesta a ping externo (Sin Internet).")
            return True 
    
    def disconnect_wifi(self):
        print("🔌 Apagando adaptador cliente WiFi...")
        try:
            if self.wifi_config_file.exists():
                self.backup_netplan_config()
                self.run_command(['rm', '-f', str(self.wifi_config_file)], sudo=True)
                self.run_command(['netplan', 'apply'], sudo=True)
            
            if self.run_command(['ip', 'link', 'set', self.client_interface, 'down'], sudo=True) is not None:
                print(f"✅ Interfaz cliente '{self.client_interface}' apagada.")
        except Exception as e:
            print(f"❌ Error apagando WiFi: {e}")

    # ==========================================
    # LÓGICA DINÁMICA DEL MODO MANTENIMIENTO
    # ==========================================
    def configure_ap_credentials(self):
        """Permite al usuario cambiar el SSID y la clave del AP"""
        print(f"\n⚙️  Configuración actual del Hotspot:")
        print(f"   SSID: {self.ap_ssid}")
        print(f"   Contraseña: {self.ap_password}")
        
        new_ssid = input("\nNuevo Nombre (SSID) [Dejar en blanco para mantener actual]: ").strip()
        if new_ssid:
            self.ap_ssid = new_ssid
            
        while True:
            new_pass = input("Nueva Contraseña (mínimo 8 caracteres) [Blanco para mantener]: ").strip()
            if not new_pass:
                break
            if len(new_pass) >= 8:
                self.ap_password = new_pass
                break
            else:
                print("❌ La contraseña de WPA2 debe tener al menos 8 caracteres.")
                
        print(f"✅ Credenciales listas: SSID='{self.ap_ssid}', Pass='{self.ap_password}'")

    def select_ap_interface_interactive(self):
        """Selecciona de forma dinámica qué tarjeta usar para el Hotspot"""
        all_ifaces = self.get_all_wireless_interfaces()
        
        # Filtramos USBs (wlx) y tarjetas internas (wlp/wlan)
        externals = [i for i in all_ifaces if i.startswith('wlx')]
        internals = [i for i in all_ifaces if not i.startswith('wlx')]
        
        if len(externals) == 1:
            print(f"✅ Adaptador USB detectado automáticamente: {externals[0]}")
            return externals[0]
            
        elif len(externals) > 1:
            print("\n📡 Múltiples adaptadores externos detectados:")
            for idx, iface in enumerate(externals, 1):
                print(f"  {idx}. {iface}")
            while True:
                try:
                    choice = int(input("Selecciona el número del adaptador a usar para el AP: "))
                    if 1 <= choice <= len(externals):
                        return externals[choice-1]
                    print("❌ Selección inválida.")
                except ValueError:
                    print("❌ Por favor ingresa un número.")
                    
        else:
            # Caso Extremo: No hay adaptadores USB conectados
            if internals:
                internal = internals[0]
                print(f"\n⚠️  ¡ATENCIÓN! No se detectaron adaptadores USB.")
                print(f"La única opción disponible es la tarjeta interna ({internal}).")
                print("🚨 Si continúas, SE CORTARÁ TU CONEXIÓN A INTERNET ACTUAL.")
                confirm = input("¿Deseas generar el AP usando la tarjeta interna? (s/n): ").strip().lower()
                if confirm == 's':
                    return internal
            else:
                print("❌ No hay tarjetas inalámbricas de ningún tipo en el sistema.")
            return None

    def start_hotspot(self):
        # 1. Seleccionar dinámicamente la interfaz
        self.ap_interface = self.select_ap_interface_interactive()
        if not self.ap_interface:
            print("🚫 Operación de Hotspot cancelada.")
            return

        print(f"\n🔥 Iniciando Punto de Acceso en {self.ap_interface}...")

        # 2. Si se eligió la interna, desconectar de internet primero
        if self.ap_interface == self.client_interface:
            print("⚠️  Desvinculando cliente de internet para liberar hardware...")
            self.disconnect_wifi()

        self.stop_hotspot(silent=True)

        try:
            # 3. Crear archivos de configuración con las credenciales dinámicas
            hostapd_conf = "/etc/ap_hostapd.conf"
            with open(hostapd_conf, 'w') as f:
                f.write(f"interface={self.ap_interface}\n")
                f.write("driver=nl80211\n")
                f.write(f"ssid={self.ap_ssid}\n")
                f.write("hw_mode=g\n")
                f.write("channel=6\n")
                f.write("wpa=2\n")
                f.write(f"wpa_passphrase={self.ap_password}\n")
                f.write("wpa_key_mgmt=WPA-PSK\n")
                f.write("rsn_pairwise=CCMP\n")

            dnsmasq_conf = "/etc/ap_dnsmasq.conf"
            with open(dnsmasq_conf, 'w') as f:
                f.write(f"interface={self.ap_interface}\n")
                f.write("bind-dynamic\n")
                f.write("dhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,12h\n")

            # 4. Levantar la red
            print("⚙️  Configurando enrutamiento de red local...")
            self.run_command(['ip', 'link', 'set', self.ap_interface, 'down'], sudo=True)
            self.run_command(['ip', 'addr', 'flush', 'dev', self.ap_interface], sudo=True)
            self.run_command(['ip', 'addr', 'add', '192.168.4.1/24', 'dev', self.ap_interface], sudo=True)
            self.run_command(['ip', 'link', 'set', self.ap_interface, 'up'], sudo=True)
            self.run_command(['rfkill', 'unblock', 'wifi'], sudo=True)

            # 5. Iniciar Demonios
            print("⏳ Levantando hostapd y dnsmasq...")
            subprocess.Popen(['sudo', 'hostapd', '-B', hostapd_conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(2)
            subprocess.Popen(['sudo', 'dnsmasq', '-C', dnsmasq_conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            print(f"\n✅ ¡HOTSPOT ACTIVADO EXITOSAMENTE!")
            print(f"📱 Conéctate desde tu teléfono o laptop:")
            print(f"   Red (SSID): {self.ap_ssid}")
            print(f"   Contraseña: {self.ap_password}")
            print(f"   Comando SSH: ssh usuario@192.168.4.1\n")

        except Exception as e:
            print(f"❌ Error iniciando Hotspot: {e}")

    def stop_hotspot(self, silent=False):
        if not self.ap_interface and not silent:
            print("⚠️  No hay un Hotspot activo para detener.")
            return

        if not silent: print(f"🔌 Deteniendo Punto de Acceso en {self.ap_interface}...")
            
        self.run_command(['pkill', '-f', 'hostapd -B /etc/ap_hostapd.conf'], sudo=True)
        self.run_command(['pkill', '-f', 'dnsmasq -C /etc/ap_dnsmasq.conf'], sudo=True)
        
        if self.ap_interface:
            self.run_command(['ip', 'addr', 'flush', 'dev', self.ap_interface], sudo=True)
            self.run_command(['ip', 'link', 'set', self.ap_interface, 'down'], sudo=True)
            
        if not silent: print("✅ Hotspot detenido y adaptador apagado.")

def main():
    manager = NetplanWiFiManager()
    
    while True:
        print("\n" + "="*60)
        print(f"📡 GESTOR DE REDES Y AP (Modo Servidor)")
        print(f"   Cliente Principal: {manager.client_interface}")
        print("="*60)
        print("1. Escanear redes disponibles")
        print("2. Conectar a red WiFi (DHCP)")
        print("3. Conectar a red WiFi (IP estática)")
        print("4. Ver estado de conexión")
        print("5. Apagar WiFi Cliente")
        print("-" * 60)
        print("6. ⚙️  Configurar Hotspot (Nombre y Contraseña)")
        print("8. 🟢 Iniciar AP (Modo Mantenimiento)")
        print("9. 🔴 Detener AP")
        print("-" * 60)
        print("0. Salir")
        print("="*60)
        
        choice = input("Selecciona una opción: ").strip()
        
        if choice == '1':
            networks = manager.scan_wifi_networks()
            if networks:
                print("\n📶 Redes disponibles:")
                for i, network in enumerate(networks, 1):
                    señal = f" [Señal: {network['signal']}]" if network['signal'] else ""
                    print(f"  {i}. {network['essid']} - {network['encryption']}{señal}")
        
        elif choice == '2':
            ssid = input("Nombre de la red (SSID) [Blanco para cancelar]: ").strip()
            if not ssid: continue
            
            password = None
            while True:
                encryption = input("¿La red tiene contraseña? (s/n) [Blanco para cancelar]: ").strip().lower()
                if not encryption: break
                if encryption == 's':
                    password = input("Contraseña: ").strip()
                    break
                elif encryption == 'n': break
                else: print("❌ Ingresa 's' para Sí, o 'n' para No.")
            
            if not encryption: continue
            
            if manager.connect_to_wifi(ssid, password): print(f"✅ Proceso finalizado.")
            else: print(f"❌ Error durante la conexión.")
        
        elif choice == '3':
            ssid = input("Nombre de la red (SSID) [Blanco para cancelar]: ").strip()
            if not ssid: continue
            
            password = None
            while True:
                encryption = input("¿La red tiene contraseña? (s/n) [Blanco para cancelar]: ").strip().lower()
                if not encryption: break
                if encryption == 's':
                    password = input("Contraseña: ").strip()
                    break
                elif encryption == 'n': break
                else: print("❌ Ingresa 's' para Sí, o 'n' para No.")
            
            if not encryption: continue
            
            ip = input("Dirección IP (ej: 192.168.1.100/24) [Blanco para cancelar]: ").strip()
            if not ip: continue
            try: ipaddress.ip_interface(ip)
            except ValueError:
                print("❌ Formato de IP inválido.")
                continue

            gateway = input("Gateway o Puerta de Enlace (ej: 192.168.1.1): ").strip()
            dns_input = input("DNS (separados por coma, ej: 8.8.8.8,1.1.1.1): ").strip()
            dns = [d.strip() for d in dns_input.split(',')] if dns_input else []
            
            manager.connect_to_wifi(ssid, password, dhcp=False, static_ip={'address': ip, 'gateway': gateway, 'dns': dns})
        
        elif choice == '4':
            manager.check_connection()
        elif choice == '5':
            manager.disconnect_wifi()
        elif choice == '6':
            manager.configure_ap_credentials()
        elif choice == '8':
            manager.start_hotspot()
        elif choice == '9':
            manager.stop_hotspot()
        elif choice == '0':
            print("👋 ¡Hasta luego!")
            break
        else:
            print("❌ Opción no válida")
        
        input("\nPresiona Enter para continuar...")

if __name__ == "__main__":
    if os.geteuid() != 0:
        print("🔒 Este script requiere permisos de superusuario (sudo).")
        sys.exit(1)
    
    tools = ['netplan', 'iw', 'ip', 'wpa_supplicant', 'hostapd', 'dnsmasq']
    missing_tools = [tool for tool in tools if shutil.which(tool) is None]
    
    if missing_tools:
        print("❌ Faltan herramientas necesarias en el sistema:")
        for tool in missing_tools: print(f"  - {tool}")
        print("\nEjecuta: sudo apt update && sudo apt install netplan.io iw iproute2 wpasupplicant hostapd dnsmasq")
        sys.exit(1)
            
    main()