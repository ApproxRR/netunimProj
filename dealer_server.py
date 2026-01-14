import socket
import struct
import threading
import time
import random

# --- Protocol Constants ---
MAGIC_COOKIE = 0xabcddcba 
UDP_PORT = 13122          
OFFER_TYPE = 0x2          
REQUEST_TYPE = 0x3        
PAYLOAD_TYPE = 0x4        
SERVER_NAME = "Nadav's Rocking Casino".ljust(32)[:32] 

class BlackijeckyServer:
    def __init__(self, host='0.0.0.0'):
        """Initializes the server and global casino statistics."""
        self.host = host
        self.tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.tcp_sock.bind((self.host, 0))
        self.tcp_port = self.tcp_sock.getsockname()[1]
        self.tcp_sock.listen(10)
        
        # Global stats across all players
        self.total_wins = 0
        self.total_losses = 0
        self.total_ties = 0
        self.stats_lock = threading.Lock() # Ensures thread-safety for global stats

    def broadcast_offers(self):
        """Broadcasts server presence every second."""
        broadcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        packet = struct.pack('>IBH32s', MAGIC_COOKIE, OFFER_TYPE, self.tcp_port, SERVER_NAME.encode())
        
        print(f"🎸 Casino is open! Broadcasting on port {self.tcp_port}...")
        while True:
            try:
                broadcast_sock.sendto(packet, ('<broadcast>', UDP_PORT))
                time.sleep(1) # Frequency limit
            except Exception as e:
                print(f"Broadcast error: {e}")

    def deal_card(self):
        """Standard 52-card deck logic."""
        rank = random.randint(1, 13) 
        suit = random.randint(0, 3)  
        if rank == 1: value = 11      
        elif rank >= 11: value = 10   
        else: value = rank           
        return rank, suit, value

    def update_global_stats(self, result):
        """Thread-safe update of the casino win/loss records."""
        with self.stats_lock:
            if result == 0x3: self.total_losses += 1 # Server loss = Player win
            elif result == 0x2: self.total_wins += 1 # Server win = Player loss
            else: self.total_ties += 1
            
            total_games = self.total_wins + self.total_losses + self.total_ties
            win_pct = (self.total_wins / total_games) * 100
            print(f"📊 [CASINO STATS] Total Games: {total_games} | House Win Rate: {win_pct:.1f}%")

    def handle_client(self, conn, addr):
        """Manages a player's session with detailed activity logging."""
        try:
            data = conn.recv(1024)
            if not data or len(data) < 38: return
            
            cookie, msg_type, rounds, team_name = struct.unpack('>IBB32s', data[:38])
            if cookie != MAGIC_COOKIE or msg_type != REQUEST_TYPE: return
            
            team_name = team_name.decode(errors='ignore').strip('\x00')
            print(f"\n🔥 [NEW PLAYER] Team '{team_name}' connected from {addr[0]}")
            print(f"🃏 Preparing to play {rounds} rounds...")

            for r_idx in range(rounds):
                print(f"--- Round {r_idx + 1} with {team_name} ---")
                result = self.play_round(conn, team_name)
                self.update_global_stats(result)
                
            print(f"🤘 Session finished for {team_name}. Connection closing.")
        except Exception as e:
            print(f"⚠️ [ERROR] Connection with {addr} failed: {e}")
        finally:
            conn.close()

    def play_round(self, conn, team_name):
        """Executes the round and prints every step of the game."""
        # Initial Deal
        p_c1_r, p_c1_s, p_c1_v = self.deal_card()
        p_c2_r, p_c2_s, p_c2_v = self.deal_card()
        d_c1_r, d_c1_s, d_c1_v = self.deal_card() 
        d_c2_r, d_c2_s, d_c2_v = self.deal_card() 

        player_sum = p_c1_v + p_c2_v
        dealer_sum = d_c1_v + d_c2_v

        print(f"   Dealing initial cards to {team_name}...")
        for r, s in [(p_c1_r, p_c1_s), (p_c2_r, p_c2_s), (d_c1_r, d_c1_s)]:
            self.send_payload(conn, 0x0, r, s)

        # Player Phase
        while player_sum <= 21:
            data = conn.recv(1024)
            if not data: break
            _, _, decision_bytes = struct.unpack('>IB5s', data)
            decision = decision_bytes.decode().strip('\x00').strip()

            print(f"   {team_name} chose to: {decision}")
            if decision == "Hittt":
                r, s, v = self.deal_card()
                player_sum += v
                print(f"   -> Dealt rank {r}. {team_name} total is now {player_sum}.")
                self.send_payload(conn, 0x0, r, s)
            else:
                break

        # Dealer Phase
        print(f"   Revealing dealer's hidden card (rank {d_c2_r})...")
        self.send_payload(conn, 0x0, d_c2_r, d_c2_s)
        
        if player_sum <= 21:
            while dealer_sum < 17:
                r, s, v = self.deal_card()
                dealer_sum += v
                print(f"   -> Dealer hits! Draws rank {r}. Dealer total: {dealer_sum}.")
                self.send_payload(conn, 0x0, r, s)
            print(f"   Dealer stands at {dealer_sum}.")

        # Decide Outcome
        result = 0x1 
        if player_sum > 21: 
            result = 0x2
            print(f"   Result: {team_name} Busted! House wins.")
        elif dealer_sum > 21: 
            result = 0x3
            print(f"   Result: Dealer Busted! {team_name} wins.")
        elif player_sum > dealer_sum: 
            result = 0x3
            print(f"   Result: {team_name} ({player_sum}) beats Dealer ({dealer_sum}).")
        elif dealer_sum > player_sum: 
            result = 0x2
            print(f"   Result: Dealer ({dealer_sum}) beats {team_name} ({player_sum}).")
        else:
            print(f"   Result: It's a tie at {player_sum} points.")
        
        self.send_payload(conn, result, 0, 0)
        return result

    def send_payload(self, conn, result, rank, suit):
        """Binary encoding for game messages."""
        rank_h, rank_l = (rank >> 8) & 0xFF, rank & 0xFF
        packet = struct.pack('>IBB3B', MAGIC_COOKIE, PAYLOAD_TYPE, result, rank_h, rank_l, suit)
        conn.send(packet)

    def run(self):
        """Starts discovery and handles multiple concurrent players."""
        threading.Thread(target=self.broadcast_offers, daemon=True).start()
        while True:
            conn, addr = self.tcp_sock.accept()
            # New thread per player ensures parallel gameplay
            threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    server = BlackijeckyServer()
    server.run()