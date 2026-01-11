#!/usr/bin/env python3
import serial
import sys
import json
import logging
import os
import argparse
from datetime import datetime
import networkx as nx
import matplotlib.pyplot as plt
from collections import defaultdict
import threading
import time
import struct




SERIAL_PORT     = "/dev/tty.usbserial-22440"    # Update with your serial port
SERIAL_BAUD     = 1000000                       # Baud rate for Sonoff ZBDongle-E   
SERIAL_CHANNEL  = 24                            # Default Zigbee channel
LOGFILE_PATH    = "~/Downloads/topology.txt"    # update to your desired log file path
UPDATE_INTERVAL = 2.0                           # number of seconds between visualiser updates

# Device name lookup - map network addresses to friendly names
# Update these to match your device addresses and names
DEVICE_NAMES = {
    '0x0000': 'Hub',
    '0xbeb2': 'Hallway',
    '0xc765': 'Utility',
    '0x4b93': 'Lounge',
    '0x0e66': 'TV room',
    '0xee58': 'Kitchen',
    '0x763f': 'Gym',
    '0x92b2': "Bed 1",
    '0x0946': "Bed 2",
    '0x2938': 'Landing',
    '0x4701': "Off 2",
    '0x776c': "Off 1",
    '0x2f9d': 'TRs',
    '0xf375': 'HW',
    '0xc4d6': 'Rads',
    '0x99ae': 'Bath 2',
    '0xd97c': 'Porch',
    '0xbc81': 'Ensuite'
}

# Zigbee broadcast and group addresses to filter out
ZIGBEE_BROADCAST_ADDRESSES = {'0xfffa', '0xfffb', '0xfffc', '0xfffd', '0xffff'}

# Hub device names for visualization layout
HUB_DEVICES = {'Hub'}

logger = logging.getLogger(__name__)


class MeshVisualizer:
    def __init__(self, update_interval=UPDATE_INTERVAL, channel=SERIAL_CHANNEL):
        """Real-time mesh network visualizer"""
        self.G = nx.DiGraph()
        self.connections = defaultdict(lambda: {'count': 0, 'avg_lqi': 0, 'avg_rssi': 0})
        self.update_interval = update_interval
        self.channel = channel
        self.last_update = time.time()
        self.lock = threading.Lock()
        
        # Set up interactive plotting
        plt.ion()
        self.fig, self.ax = plt.subplots(figsize=(14, 10))
        self.fig.canvas.manager.set_window_title('Zigbee Mesh Network - Live')
        
    def add_connection(self, src, dst, lqi, rssi):
        """Add or update a connection in the mesh"""
        with self.lock:
            # Add nodes if they don't exist
            if src not in self.G:
                self.G.add_node(src)
            if dst not in self.G:
                self.G.add_node(dst)
            
            # Update connection statistics
            key = (src, dst)
            conn = self.connections[key]
            old_count = conn['count']
            conn['count'] += 1
            conn['avg_lqi'] = (conn['avg_lqi'] * old_count + lqi) / conn['count']
            conn['avg_rssi'] = (conn['avg_rssi'] * old_count + rssi) / conn['count']
            
            # Add/update edge
            if self.G.has_edge(src, dst):
                self.G[src][dst]['weight'] += 1
            else:
                self.G.add_edge(src, dst, weight=1)
            
            self.G[src][dst]['lqi'] = conn['avg_lqi']
            self.G[src][dst]['rssi'] = conn['avg_rssi']
    
    def should_update(self):
        """Check if it's time to update the visualization"""
        return time.time() - self.last_update >= self.update_interval
    
    def update_plot(self):
        """Redraw the network visualization"""
        if self.G.number_of_nodes() == 0:
            return
        
        with self.lock:
            self.ax.clear()
            
            # Separate hub from devices
            hub_nodes = [n for n in self.G.nodes() if n in HUB_DEVICES]
            device_nodes = [n for n in self.G.nodes() if n not in hub_nodes]
            
            # Use shell layout: hub in center, devices in circle around it
            if hub_nodes:
                shells = [hub_nodes, device_nodes] if device_nodes else [hub_nodes]
                pos = nx.shell_layout(self.G, nlist=shells, scale=2)
            else:
                # If no hub yet, use circular layout for all devices
                pos = nx.circular_layout(self.G, scale=2)
            
            # Draw hub nodes
            if hub_nodes:
                nx.draw_networkx_nodes(self.G, pos, nodelist=hub_nodes,
                                     ax=self.ax, node_color='red', 
                                     node_size=3000, node_shape='s', 
                                     label='Hub')
            
            # Draw device nodes
            if device_nodes:
                nx.draw_networkx_nodes(self.G, pos, nodelist=device_nodes,
                                     ax=self.ax, node_color='lightblue',
                                     node_size=2000, node_shape='o',
                                     label='Devices')
            
            # Draw edges with thickness based on traffic
            if self.G.number_of_edges() > 0:
                edges = list(self.G.edges())
                weights = [self.G[u][v]['weight'] for u, v in edges]
                max_weight = max(weights) if weights else 1
                
                nx.draw_networkx_edges(self.G, pos, ax=self.ax,
                                     width=[w/max_weight * 3 for w in weights],
                                     alpha=0.9, arrows=True, arrowsize=15,
                                     edge_color='black',
                                     connectionstyle='arc3,rad=0.1')
                
                # Edge labels showing LQI
                edge_labels = {(u, v): f"{int(self.G[u][v]['lqi'])}" for u, v in edges}
                nx.draw_networkx_edge_labels(self.G, pos, edge_labels,
                                           ax=self.ax, font_size=7)
            
            # Draw node labels
            nx.draw_networkx_labels(self.G, pos, ax=self.ax,
                                  font_size=9, font_weight='bold')
            
            # Title with stats
            self.ax.set_title(
                f'Zigbee Mesh Network - Live (Channel {self.channel})\n'
                f'Nodes: {self.G.number_of_nodes()} | '
                f'Connections: {self.G.number_of_edges()} | '
                f'Messages: {sum(d["weight"] for _, _, d in self.G.edges(data=True))}',
                fontsize=14, fontweight='bold'
            )
            
            if hub_nodes or device_nodes:
                self.ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1), 
                              framealpha=0.9, fontsize=10, borderaxespad=0,
                              labelspacing=1.5, handletextpad=1.5, markerscale=0.5)
            self.ax.axis('off')
            
            # Adjust layout to make room for legend
            plt.subplots_adjust(right=0.85)
            plt.draw()
            plt.pause(0.001)  # Small pause to allow GUI update
            
            self.last_update = time.time()


def get_device_name(nwk_addr):
    """Convert network address to device name or return address if unknown"""
    return DEVICE_NAMES.get(nwk_addr, nwk_addr)

def parse_802154_frame(raw_bytes):
    """Parse IEEE 802.15.4 frame"""
    if len(raw_bytes) < 5:
        return None
    
    # Frame Control Field (2 bytes, little-endian)
    fcf = struct.unpack('<H', raw_bytes[0:2])[0]
    
    # Parse FCF bits
    frame_type = fcf & 0x07
    security_enabled = (fcf >> 3) & 0x01
    frame_pending = (fcf >> 4) & 0x01
    ack_request = (fcf >> 5) & 0x01
    pan_id_compression = (fcf >> 6) & 0x01
    dest_addr_mode = (fcf >> 10) & 0x03
    frame_version = (fcf >> 12) & 0x03
    src_addr_mode = (fcf >> 14) & 0x03
    
    # Sequence number (1 byte)
    seq_num = raw_bytes[2]
    
    offset = 3
    dest_pan_id = None
    dest_addr = None
    src_pan_id = None
    src_addr = None
    
    # Destination PAN ID (2 bytes if present)
    if dest_addr_mode > 0:
        dest_pan_id = struct.unpack('<H', raw_bytes[offset:offset+2])[0]
        offset += 2
    
    # Destination Address
    if dest_addr_mode == 2:  # 16-bit short address
        dest_addr = struct.unpack('<H', raw_bytes[offset:offset+2])[0]
        offset += 2
    elif dest_addr_mode == 3:  # 64-bit extended address
        dest_addr = struct.unpack('<Q', raw_bytes[offset:offset+8])[0]
        offset += 8
    
    # Source PAN ID (2 bytes if not compressed)
    if src_addr_mode > 0 and not pan_id_compression:
        src_pan_id = struct.unpack('<H', raw_bytes[offset:offset+2])[0]
        offset += 2
    elif pan_id_compression:
        src_pan_id = dest_pan_id
    
    # Source Address
    if src_addr_mode == 2:  # 16-bit short address
        src_addr = struct.unpack('<H', raw_bytes[offset:offset+2])[0]
        offset += 2
    elif src_addr_mode == 3:  # 64-bit extended address
        src_addr = struct.unpack('<Q', raw_bytes[offset:offset+8])[0]
        offset += 8
    
    return {
        'fcf': fcf,
        'frame_type': frame_type,
        'security_enabled': security_enabled,
        'frame_pending': frame_pending,
        'ack_request': ack_request,
        'pan_id_compression': pan_id_compression,
        'dest_addr_mode': dest_addr_mode,
        'src_addr_mode': src_addr_mode,
        'seq_num': seq_num,
        'dest_pan_id': f'0x{dest_pan_id:04x}' if dest_pan_id else None,
        'dest_addr': f'0x{dest_addr:04x}' if dest_addr and dest_addr_mode == 2 else f'0x{dest_addr:016x}' if dest_addr else None,
        'src_pan_id': f'0x{src_pan_id:04x}' if src_pan_id else None,
        'src_addr': f'0x{src_addr:04x}' if src_addr and src_addr_mode == 2 else f'0x{src_addr:016x}' if src_addr else None,
        'payload_offset': offset
    }

def parse_zigbee_nwk(raw_bytes, mac_offset):
    """Parse Zigbee NWK header starting at mac_offset"""
    if len(raw_bytes) < mac_offset + 8:
        return None
    
    offset = mac_offset
    
    # NWK Frame Control (2 bytes, little-endian)
    nwk_fcf = struct.unpack('<H', raw_bytes[offset:offset+2])[0]
    offset += 2
    
    # Parse NWK FCF bits
    frame_type = nwk_fcf & 0x03
    protocol_version = (nwk_fcf >> 2) & 0x0F
    discover_route = (nwk_fcf >> 6) & 0x03
    multicast = (nwk_fcf >> 8) & 0x01
    security = (nwk_fcf >> 9) & 0x01
    source_route = (nwk_fcf >> 10) & 0x01
    dest_ieee_present = (nwk_fcf >> 11) & 0x01
    src_ieee_present = (nwk_fcf >> 12) & 0x01
    
    # Destination Address (2 bytes)
    nwk_dst = struct.unpack('<H', raw_bytes[offset:offset+2])[0]
    offset += 2
    
    # Source Address (2 bytes)
    nwk_src = struct.unpack('<H', raw_bytes[offset:offset+2])[0]
    offset += 2
    
    # Radius (1 byte)
    radius = raw_bytes[offset]
    offset += 1
    
    # Sequence Number (1 byte)
    nwk_seq = raw_bytes[offset]
    offset += 1
    
    # Optional fields
    dst_ieee = None
    src_ieee = None
    multicast_control = None
    source_route_frame = None
    
    if dest_ieee_present:
        dst_ieee = struct.unpack('<Q', raw_bytes[offset:offset+8])[0]
        offset += 8
    
    if src_ieee_present:
        src_ieee = struct.unpack('<Q', raw_bytes[offset:offset+8])[0]
        offset += 8
    
    if multicast:
        multicast_control = raw_bytes[offset]
        offset += 1
    
    if source_route:
        # Check if we have enough bytes for relay count and index
        if offset + 2 > len(raw_bytes):
            return None
        
        relay_count = raw_bytes[offset]
        relay_index = raw_bytes[offset + 1]
        offset += 2
        relay_list = []
        
        # Check if we have enough bytes for all relay addresses (2 bytes each)
        if offset + (relay_count * 2) > len(raw_bytes):
            # Packet is truncated, only read what's available
            relay_count = (len(raw_bytes) - offset) // 2
        
        for i in range(relay_count):
            relay = struct.unpack('<H', raw_bytes[offset:offset+2])[0]
            relay_list.append(f'0x{relay:04x}')
            offset += 2
        source_route_frame = {
            'relay_count': relay_count,
            'relay_index': relay_index,
            'relay_list': relay_list
        }
    
    return {
        'nwk_fcf': f'0x{nwk_fcf:04x}',
        'frame_type': frame_type,
        'protocol_version': protocol_version,
        'discover_route': discover_route,
        'security': security,
        'source_route': source_route,
        'dest_ieee_present': dest_ieee_present,
        'src_ieee_present': src_ieee_present,
        'nwk_dst': f'0x{nwk_dst:04x}',
        'nwk_src': f'0x{nwk_src:04x}',
        'radius': radius,
        'nwk_seq': nwk_seq,
        'dst_ieee': f'0x{dst_ieee:016x}' if dst_ieee else None,
        'src_ieee': f'0x{src_ieee:016x}' if src_ieee else None,
        'source_route_frame': source_route_frame,
        'payload_offset': offset
    }


def dump_frame(hex_string, lqi=0, rssi=0, visualizer=None):
    """Dump frame information"""
    raw_data = bytearray.fromhex(hex_string)
    
    # Parse 802.15.4
    mac = parse_802154_frame(raw_data)
    if mac:
        # If it's a data frame (type 1) and not a broadcast, parse Zigbee NWK
        if mac['frame_type'] == 1 and mac['dest_addr'] != '0xffff':
            nwk = parse_zigbee_nwk(raw_data, mac['payload_offset'])
            if nwk:
                if nwk['source_route_frame']:
                    sr = nwk['source_route_frame']
                    if (sr['relay_count'] > 0):
                        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                        src_name = get_device_name(nwk['nwk_src'])
                        dst_name = get_device_name(nwk['nwk_dst'])
                        relay_names = [get_device_name(addr) for addr in sr['relay_list']]

                        print(f"[{timestamp}] LQI:{lqi:3d} RSSI:{rssi:4d} {src_name} -> {' -> '.join(relay_names)} -> {dst_name}")
                        logger.info(f"[{timestamp}] LQI:{lqi:3d} RSSI:{rssi:4d} {src_name} -> {' -> '.join(relay_names)} -> {dst_name}")

                        # Add to visualiser (skip broadcast and group addresses)
                        if visualizer and nwk['nwk_dst'] not in ZIGBEE_BROADCAST_ADDRESSES:
                            devices = [src_name] + relay_names + [dst_name]
                            for i in range(len(devices) - 1):
                                visualizer.add_connection(devices[i], devices[i+1], lqi, rssi)
                        
                    else :
                        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                        src_name = get_device_name(nwk['nwk_src'])
                        dst_name = get_device_name(nwk['nwk_dst'])
                        print(f"[{timestamp}] LQI:{lqi:3d} RSSI:{rssi:4d} {src_name} -> {dst_name} ")
                        logger.info(f"[{timestamp}] LQI:{lqi:3d} RSSI:{rssi:4d} {src_name} -> {dst_name} ")
                        
                        # Add to visualiser (skip broadcast addresses)
                        if visualizer and nwk['nwk_dst'] not in ZIGBEE_BROADCAST_ADDRESSES:
                            visualizer.add_connection(src_name, dst_name, lqi, rssi)
                else:
                    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                    src_name = get_device_name(nwk['nwk_src'])
                    dst_name = get_device_name(nwk['nwk_dst'])
                    print(f"[{timestamp}] LQI:{lqi:3d} RSSI:{rssi:4d} {src_name} -> {dst_name} ")
                    logger.info(f"[{timestamp}] LQI:{lqi:3d} RSSI:{rssi:4d} {src_name} -> {dst_name} ")
                    
                    # Add to visualizer (skip broadcast addresses)
                    if visualizer and nwk['nwk_dst'] not in ZIGBEE_BROADCAST_ADDRESSES:
                        visualizer.add_connection(src_name, dst_name, lqi, rssi)


def main():
    """Main entry point for the mesh visualizer"""
    parser = argparse.ArgumentParser(description='Zigbee Mesh Network Visualizer')
    parser.add_argument('-p', '--port', default=SERIAL_PORT, help=f'Serial port (default: {SERIAL_PORT})')
    parser.add_argument('-b', '--baud', type=int, default=SERIAL_BAUD, help=f'Baud rate (default: {SERIAL_BAUD})')
    parser.add_argument('-c', '--channel', type=int, default=SERIAL_CHANNEL, help=f'Zigbee channel (default: {SERIAL_CHANNEL})')
    parser.add_argument('-l', '--logfile', default=LOGFILE_PATH, help=f'Log file path (default: {LOGFILE_PATH})')
    parser.add_argument('-u', '--update-interval', type=float, default=UPDATE_INTERVAL, help=f'Update interval in seconds (default: {UPDATE_INTERVAL})')
    args = parser.parse_args()
    
    try:
        logging.basicConfig(filename=os.path.expanduser(args.logfile), filemode="a", level=logging.INFO)

        ser = serial.Serial(args.port, args.baud, timeout=1)

        channel = str(args.channel)
        ser.write(bytes('{"C":', 'utf-8') + bytes(channel, 'utf-8') + bytes('}\r\n', 'utf-8'))

        # Initialize real-time visualizer
        print("Starting real-time mesh visualization...")
        visualizer = MeshVisualizer(update_interval=args.update_interval, channel=args.channel)

    except Exception as e:
        print("Error opening serial port:", e)
        sys.exit(1)

    try:
        while True:
            data = ser.readline().decode('utf-8', errors='ignore').strip()

            if not data:
                continue

            try:
                json_obj  = json.loads(data)
                lqi       = json_obj.get('Q', 0)
                rssi      = json_obj.get('R', 0)
                payload   = json_obj.get('S', 0)
                # chan    = json_obj.get('C', 0) unused
                # length  = json_obj.get('L', 0) unused

                dump_frame(payload, lqi, rssi, visualizer)
                
                # Update visualisation periodically
                if visualizer.should_update():
                    visualizer.update_plot()

            except json.JSONDecodeError as e:
                print(f'JSONDecodeError:{e}')

    except KeyboardInterrupt:
        print("\nStopping capture...")
        plt.ioff()
        plt.show()  # Keep final plot open


if __name__ == "__main__":
    main()


