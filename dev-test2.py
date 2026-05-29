#!/usr/bin/env python3
"""
Gestor de Redes WiFi y Hotspot para Ubuntu Server
Integración total AP/Cliente con Interfaz Limpia (v2.0)
"""

import subprocess
import os
import sys
import time
import yaml
import shutil
import ipaddress
from pathlib import Path

def clear_screen():
    """Limpia la terminal para una interfaz más ordenada"""
    os.system('clear')

def pause():
    """Pausa la ejecución para que el usuario pueda leer la salida antes de limpiar"""
    input("\nPresiona [ENTER] para continuar...")

class NetplanWiFiManager:
    def __init__(self):
        self.netplan_dir = Path('/etc/netplan')
        self.backup_dir = Path('/etc/netplan/backups')
        self.backup_dir.mkdir(exist_ok=True)
        self.wifi_config_file = self.netplan_dir / '99-wifi-config.yaml'
        
        self.ap_ssid = "Servidor_Mantenimiento"
        self.ap_password = "acceso_local_123"
        
        self.client_interface = self.get_internal_interface()
        self.ap_interface = None 
        
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
        interfaces = []
        try:
            result = subprocess.run(['ip', '-br', 'link', 'show'], capture_output=True, text=True)
            if result.stdout:
                for line in result.stdout.split('\n'):
                    parts = line.split()
                    if parts:
                        iface = parts[0]
                        if iface.startswith('wl'): 
                            interfaces.append(iface)
        except:
            pass
        return interfaces
        
    def get_internal_interface(self):
        all_ifaces = self.get_all_wireless_interfaces()
        internals = [i for i in all_ifaces if not i.startswith('wlx')]
        return internals[0] if internals else (all_ifaces[0] if all_ifaces else 'wlan0')
    
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
            print("❌ Error: La interfaz sigue ocupada. Asegúrate de detener el AP primero si está encendido.")
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
    
    def get_interface_status(self):
        print(f"\n📊 Estado de la interfaz: {self.client_interface}")
        link_info = self.run_command(['iw', 'dev', self.client_interface, 'link'])
        if link_info and "Not connected" not in link_info:
            for line in link_info.split('\n'):
                line = line.strip()
                if line.startswith('SSID:'): print(f"   Red: {line.split('SSID:')[1].strip()}")
                elif line.startswith('signal:'): print(f"   Señal: {line.split('signal:')[1].strip()}")
        else:
            print("   Red: Desconectado o Apagado")
        
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
            print("❌ Sin IP asignada en el cliente. Revisa router o DHCP.")
            return False
        try:
            subprocess.run(['ping', '-c', '3', '-W', '5', '8.8.8.8'], capture_output=True, check=True)
            print("✅ Conexión a Internet activa")
            return True
        except subprocess.CalledProcessError:
            print("⚠️  Sin respuesta a ping externo (Sin Internet).")
            return True 

    def enable_wifi(self):
        print(f"🔌 Encendiendo adaptador cliente ({self.client_interface})...")
        try:
            if self.run_command(['ip', 'link', 'set', self.client_interface, 'up'], sudo=True) is not None:
                print(f"✅ Interfaz encendida.")
        except Exception as e:
            print(f"❌ Error encendiendo WiFi: {e}")
            
    def disconnect_wifi(self):
        print(f"🔌 Apagando adaptador cliente ({self.client_interface})...")
        try:
            if self.wifi_config_file.exists():
                self.backup_netplan_config()
                self.run_command(['rm', '-f', str(self.wifi_config_file)], sudo=True)
                self.run_command(['netplan', 'apply'], sudo=True)
            
            if self.run_command(['ip', 'link', 'set', self.client_interface, 'down'], sudo=True) is not None:
                print(f"✅ Interfaz apagada.")
        except Exception as e:
            print(f"❌ Error apagando WiFi: {e}")

    # ==========================================
    # LÓGICA DINÁMICA (CLIENTE Y HOTSPOT)
    # ==========================================
    def change_client_interface(self):
        all_ifaces = self.get_all_wireless_interfaces()
        if not all_ifaces:
            print("❌ No hay adaptadores de red detectados.")
            return
            
        print("\n📡 Selecciona el adaptador para RECIBIR Internet (Cliente WiFi):")
        for idx, iface in enumerate(all_ifaces, 1):
            tipo = "USB/Externo" if iface.startswith('wlx') else "Interno/PCI"
            actual = " [ACTUAL]" if iface == self.client_interface else ""
            print(f"  {idx}. {iface} ({tipo}){actual}")
            
        while True:
            try:
                choice = input("Ingresa el número [Blanco para cancelar]: ").strip()
                if not choice: return
                
                choice = int(choice)
                if 1 <= choice <= len(all_ifaces):
                    self.client_interface = all_ifaces[choice-1]
                    print(f"✅ Adaptador cliente cambiado a: {self.client_interface}")
                    break
                print("❌ Selección inválida.")
            except ValueError:
                print("❌ Ingresa un número válido.")

    def configure_ap_credentials(self):
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
        all_ifaces = self.get_all_wireless_interfaces()
        
        if not all_ifaces:
            print("❌ No hay tarjetas inalámbricas de ningún tipo en el sistema.")
            return None
            
        if len(all_ifaces) == 1:
            iface = all_ifaces[0]
            print(f"\n⚠️  Solo se detectó una tarjeta en todo el sistema ({iface}).")
            print("🚨 Si continúas, SE CORTARÁ TU CONEXIÓN A INTERNET ACTUAL.")
            confirm = input("¿Deseas usar esta tarjeta para el Hotspot? (s/n): ").strip().lower()
            return iface if confirm == 's' else None
            
        print("\n📡 Selecciona el adaptador para EMITIR el Hotspot (Modo AP):")
        for idx, iface in enumerate(all_ifaces, 1):
            tipo = "USB/Externo" if iface.startswith('wlx') else "Interno/PCI"
            print(f"  {idx}. {iface} ({tipo})")
            
        while True:
            try:
                choice = input("Ingresa el número [Blanco para cancelar]: ").strip()
                if not choice: return None
                
                choice = int(choice)
                if 1 <= choice <= len(all_ifaces):
                    selected = all_ifaces[choice-1]
                    if selected == self.client_interface:
                        print("\n⚠️  Elegiste la MISMA tarjeta que el Cliente Principal.")
                        confirm = input("¿Estás seguro de desconectar el internet del servidor para emitir el AP? (s/n): ").strip().lower()
                        if confirm != 's': return None
                    return selected
                print("❌ Selección inválida.")
            except ValueError:
                print("❌ Ingresa un número válido.")

    def start_hotspot(self):
        self.ap_interface = self.select_ap_interface_interactive()
        if not self.ap_interface:
            print("🚫 Operación de Hotspot cancelada.")
            return

        clear_screen()
        print(f"🔥 Iniciando Punto de Acceso en [{self.ap_interface}]...")

        if self.ap_interface == self.client_interface:
            print("⚠️  Desvinculando cliente de internet para liberar hardware...")
            self.disconnect_wifi()

        # Limpieza previa de cualquier proceso zombi
        self.run_command(['pkill', '-f', 'hostapd'], sudo=True)
        self.run_command(['pkill', '-f', 'dnsmasq'], sudo=True)
        self.run_command(['iptables', '-t', 'nat', '-F'], sudo=True)

        try:
            # 1. Dormir servicios del cliente
            print("   [1/5] Deteniendo systemd-resolved y wpa_supplicant...")
            self.run_command(['systemctl', 'stop', 'systemd-resolved'], sudo=True)
            self.run_command(['systemctl', 'stop', 'wpa_supplicant'], sudo=True)
            self.run_command(['pkill', 'wpa_supplicant'], sudo=True)

            # 2. Configurar NAT y Enrutamiento
            print("   [2/5] Configurando IP Forwarding y NAT...")
            self.run_command(['sysctl', '-w', 'net.ipv4.ip_forward=1'], sudo=True)
            
            # Verificamos si la interfaz cliente tiene IP para compartir internet
            client_ip = self.run_command(['ip', 'addr', 'show', self.client_interface])
            if client_ip and 'inet ' in client_ip and self.client_interface != self.ap_interface:
                print(f"         > Compartiendo Internet desde [{self.client_interface}]...")
                self.run_command(['iptables', '-t', 'nat', '-A', 'POSTROUTING', '-o', self.client_interface, '-j', 'MASQUERADE'], sudo=True)
            else:
                print("         > AP en modo local (Sin Internet o usando la misma tarjeta).")

            # 3. Archivos de configuración
            print("   [3/5] Generando archivos hostapd y dnsmasq...")
            with open("/etc/ap_hostapd.conf", 'w') as f:
                f.write(f"interface={self.ap_interface}\ndriver=nl80211\nssid={self.ap_ssid}\nhw_mode=g\nchannel=6\nwpa=2\nwpa_passphrase={self.ap_password}\nwpa_key_mgmt=WPA-PSK\nrsn_pairwise=CCMP\n")

            with open("/etc/ap_dnsmasq.conf", 'w') as f:
                f.write(f"interface={self.ap_interface}\nbind-dynamic\ndhcp-range=192.168.4.10,192.168.4.50,255.255.255.0,12h\ndhcp-option=3,192.168.4.1\ndhcp-option=6,8.8.8.8,8.8.4.4\n")

            # 4. Iniciar hostapd PRIMERO
            print("   [4/5] Iniciando Emisor WiFi (hostapd)...")
            self.run_command(['rfkill', 'unblock', 'wifi'], sudo=True)
            subprocess.Popen(['sudo', 'hostapd', '-B', '/etc/ap_hostapd.conf'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3) # Pausa crucial para que la tarjeta se estabilice

            # 5. Asignar IP y lanzar dnsmasq DESPUÉS
            print("   [5/5] Asignando IPs y levantando servidor DHCP (dnsmasq)...")
            self.run_command(['ip', 'addr', 'flush', 'dev', self.ap_interface], sudo=True)
            self.run_command(['ip', 'addr', 'add', '192.168.4.1/24', 'dev', self.ap_interface], sudo=True)
            self.run_command(['ip', 'link', 'set', self.ap_interface, 'up'], sudo=True)
            
            subprocess.Popen(['sudo', 'dnsmasq', '-C', '/etc/ap_dnsmasq.conf'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            print(f"\n✅ ¡HOTSPOT ACTIVADO EXITOSAMENTE!")
            print(f"📱 Conéctate desde tu teléfono o laptop:")
            print(f"   Red (SSID): {self.ap_ssid}")
            print(f"   Contraseña: {self.ap_password}")
            print(f"   Comando SSH: ssh usuario@192.168.4.1")

        except Exception as e:
            print(f"❌ Error iniciando Hotspot: {e}")

    def stop_hotspot(self):
        if not self.ap_interface:
            print("⚠️  No hay un Hotspot registrado como activo en esta sesión.")
            # Continuamos de todos modos por si se quedó pegado de una sesión anterior
            
        print(f"🔌 Deteniendo Punto de Acceso y restaurando sistema...")
        
        # 1. Limpiar reglas de NAT y matar procesos
        print("   [1/4] Limpiando procesos y reglas de enrutamiento...")
        self.run_command(['iptables', '-t', 'nat', '-F'], sudo=True)
        self.run_command(['pkill', '-f', 'hostapd'], sudo=True)
        self.run_command(['pkill', '-f', 'dnsmasq'], sudo=True)
        
        # 2. Restaurar interfaz
        iface_to_restore = self.ap_interface if self.ap_interface else self.get_internal_interface()
        print(f"   [2/4] Reiniciando tarjeta física [{iface_to_restore}]...")
        self.run_command(['ip', 'addr', 'flush', 'dev', iface_to_restore], sudo=True)
        self.run_command(['ip', 'link', 'set', iface_to_restore, 'down'], sudo=True)
        self.run_command(['ip', 'link', 'set', iface_to_restore, 'up'], sudo=True)
        
        # 3. Revivir servicios nativos de Ubuntu
        print("   [3/4] Reviviendo servicios de red de Ubuntu (DNS y WPA)...")
        self.run_command(['systemctl', 'start', 'systemd-resolved'], sudo=True)
        self.run_command(['systemctl', 'restart', 'wpa_supplicant'], sudo=True)
        
        # 4. Aplicar Netplan
        print("   [4/4] Restaurando conexión a Internet...")
        self.run_command(['netplan', 'apply'], sudo=True)
            
        self.ap_interface = None
        print("\n✅ MODO CLIENTE RESTAURADO. Ya puedes escanear y conectarte a redes WiFi.")

def settings_menu(manager):
    while True:
        clear_screen()
        print("="*50)
        print("⚙️  MENÚ DE CONFIGURACIONES")
        print("="*50)
        print("1. Ver estado de la conexión")
        print("2. Seleccionar dispositivo Cliente")
        print("3. Configuración del Hotspot")
        print("0. Volver al menú principal")
        print("="*50)
        
        choice = input("Selecciona una opción: ").strip()
        
        if choice == '1':
            clear_screen()
            manager.get_interface_status()
            manager.check_connection()
            pause()
        elif choice == '2':
            clear_screen()
            manager.change_client_interface()
            pause()
        elif choice == '3':
            clear_screen()
            manager.configure_ap_credentials()
            pause()
        elif choice == '0':
            break
        else:
            print("❌ Opción no válida")
            time.sleep(1)

def main():
    manager = NetplanWiFiManager()
    
    while True:
        clear_screen()
        print("="*60)
        print(f"📡 GESTOR DE REDES Y AP (Modo Servidor)")
        print(f"   Cliente Principal: {manager.client_interface}")
        if manager.ap_interface:
            print(f"   Hotspot Activo en: {manager.ap_interface}")
        print("="*60)
        print("1. Escanear y conectar a red WiFi")
        print("2. Conectar manualmente (DHCP)")
        print("3. Conectar manualmente (IP estática)")
        print("4. Encender WiFi Cliente")
        print("5. Apagar WiFi Cliente")
        print("-" * 60)
        print("6. ⚙️ Configuraciones")
        print("7. 🟢 Iniciar AP (Modo Mantenimiento)")
        print("8. 🔴 Detener AP (Restaurar Internet)")
        print("-" * 60)
        print("0. Salir")
        print("="*60)
        
        choice = input("Selecciona una opción: ").strip()
        
        if choice == '1':
            clear_screen()
            networks = manager.scan_wifi_networks()
            if networks:
                print("\n📶 Redes disponibles:")
                for i, network in enumerate(networks, 1):
                    señal = f" [Señal: {network['signal']}]" if network['signal'] else ""
                    print(f"  {i}. {network['essid']} - {network['encryption']}{señal}")
                print("  0. Cancelar")
                
                try:
                    sel = input("\nSelecciona el número de la red para conectar (o 0 para salir): ").strip()
                    if sel == '0' or not sel:
                        continue
                    sel = int(sel)
                    
                    if 1 <= sel <= len(networks):
                        net = networks[sel-1]
                        ssid = net['essid']
                        password = None
                        
                        if net['encryption'] != 'Abierta':
                            password = input(f"Contraseña para '{ssid}': ").strip()
                            
                        clear_screen()
                        if manager.connect_to_wifi(ssid, password):
                            print(f"\n✅ Proceso finalizado con éxito.")
                        else:
                            print(f"\n❌ Error durante la conexión.")
                        pause()
                    else:
                        print("❌ Número fuera de rango.")
                        pause()
                except ValueError:
                    print("🚫 Operación cancelada.")
                    pause()
            else:
                pause()
        
        elif choice == '2':
            clear_screen()
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
            
            clear_screen()
            if manager.connect_to_wifi(ssid, password): print(f"\n✅ Proceso finalizado.")
            else: print(f"\n❌ Error durante la conexión.")
            pause()
        
        elif choice == '3':
            clear_screen()
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
                pause()
                continue

            gateway = input("Gateway o Puerta de Enlace (ej: 192.168.1.1): ").strip()
            dns_input = input("DNS (separados por coma, ej: 8.8.8.8,1.1.1.1): ").strip()
            dns = [d.strip() for d in dns_input.split(',')] if dns_input else []
            
            clear_screen()
            manager.connect_to_wifi(ssid, password, dhcp=False, static_ip={'address': ip, 'gateway': gateway, 'dns': dns})
            pause()
        
        elif choice == '4':
            clear_screen()
            manager.enable_wifi()
            pause()
        elif choice == '5':
            clear_screen()
            manager.disconnect_wifi()
            pause()
        elif choice == '6':
            settings_menu(manager)
        elif choice == '7':
            clear_screen()
            manager.start_hotspot()
            pause()
        elif choice == '8':
            clear_screen()
            manager.stop_hotspot()
            pause()
        elif choice == '0':
            clear_screen()
            print("👋 ¡Hasta luego!")
            break
        else:
            print("❌ Opción no válida")
            time.sleep(1)

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