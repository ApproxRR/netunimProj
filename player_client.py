import socket
import struct
import time

# --- Protocol & Game Constants ---
MAGIC_COOKIE = 0xabcddcba  # Every packet must start with this header
UDP_PORT = 13122           # Mandatory port for server discovery
TEAM_NAME = "Diagonal Shooters".ljust(32)[:32]  # Fixed 32-byte name

# Mapping for pretty printing
SUITS = {0: '❤️', 1: '♦️', 2: '♣️', 3: '♠️'}
RANKS = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}

def get_card_str(rank, suit):
    """Converts numeric rank and suit into a readable string with emojis."""
    rank_name = RANKS.get(rank, str(rank))
    suit_emoji = SUITS.get(suit, '')
    return f"{rank_name}{suit_emoji}"

def start_client():
    """Main discovery and game management loop."""
    while True:
        print("\n🎸 Straight Shooters: Waiting for a server offer...")
        
        # Listen for UDP offers from servers
        udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if hasattr(socket, 'SO_REUSEPORT'):
            udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        else:
            udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        udp_sock.bind(('', UDP_PORT))
        
        try:
            # Step 1: Discover Server
            udp_sock.settimeout(10.0) # Prevents waiting forever
            data, addr = udp_sock.recvfrom(1024)
            
            # Unpack the 39-byte offer
            if len(data) < 39: continue
            cookie, msg_type, tcp_port, server_name = struct.unpack('>IBH32s', data[:39])
            
            if cookie != MAGIC_COOKIE or msg_type != 0x2: continue
            
            print(f"🤘 Found Server: {server_name.decode(errors='ignore').strip()} at {addr[0]}")
            udp_sock.close()

            # Step 2: Play Session
            while True:
                num_rounds = int(input("How many rounds will you play? "))
                if num_rounds != 0:
                    break
                
            stats = {
                "wins": 0, "losses": 0, "ties": 0,
                "total_hits": 0, "busts": 0, "aces_drawn": 0,
                "dealer_busts": 0, "start_time": time.time()
            }

            # Connect via TCP
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_sock:
                tcp_sock.settimeout(15.0) # Handle network interferenc
                tcp_sock.connect((addr[0], tcp_port))
                
                # Send Request Packet
                request = struct.pack('>IBB32s', MAGIC_COOKIE, 0x3, num_rounds, TEAM_NAME.encode())
                tcp_sock.send(request)
                
                for r_idx in range(num_rounds):
                    print(f"\n--- Round {r_idx + 1} ---")
                    result = play_round(tcp_sock, stats)
                    if result == 0x3: stats["wins"] += 1
                    elif result == 0x2: stats["losses"] += 1
                    else: stats["ties"] += 1
                
                display_stats(num_rounds, stats)
                
        except (socket.timeout, ConnectionError) as e:
            print(f"⚠️ Network error: {e}. Back to listening...")
        except ValueError:
            print("❌ Use numbers for rounds!")
        finally:
            udp_sock.close()

def play_round(sock, stats):
    """Manages the cards and decisions for one round."""
    player_hand = []
    dealer_hand = []
    
    # Step A: Initial Deal (Server sends 2 player cards and 1 dealer card)
    for _ in range(3):
        res, rank, suit = safe_recv(sock)
        if _ < 2: 
            player_hand.append((rank, suit))
            if rank == 1: stats["aces_drawn"] += 1
        else: 
            dealer_hand.append((rank, suit))

    # Step B: Player Turn
    while True:
        p_sum = calculate_points(player_hand)
        print(f"Your Hand: {format_hand(player_hand)} (Total: {p_sum})")
        print(f"Dealer Shows: {format_hand(dealer_hand)}")
        
        if p_sum > 21:
            print("💥 BUSTED!")
            stats["busts"] += 1
            break
            
        # Ensure the input is valid before proceeding to prevent accidental stands
        while True:
            choice = input("Hit (h) or Stand (s)? ").lower().strip()
            if choice in ['h', 's']:
                break
            print("❌ Invalid input! Type 'h' to Hit or 's' to Stand.")

        # Map the single character to the 5-byte protocol string 
        decision = "Hittt" if choice == 'h' else "Stand"
        sock.send(struct.pack('>IB5s', MAGIC_COOKIE, 0x4, decision.encode().ljust(5)))
        
        if decision == "Stand": break
        
        # Get the new card from Hit
        stats["total_hits"] += 1
        res, rank, suit = safe_recv(sock)
        player_hand.append((rank, suit))
        if rank == 1: stats["aces_drawn"] += 1

    # Step C: Result Phase (Reveal Dealer Cards and Final Outcome)
    print("\n--- Dealer's Turn ---")
    while True:
        res, rank, suit = safe_recv(sock)
        
        # If the server sends a card, add it to dealer's hand and show it
        if rank != 0:
            dealer_hand.append((rank, suit))
            print(f"Dealer draws: {get_card_str(rank, suit)}")
            if calculate_points([(rank, suit)]) > 21: # Simplified dealer bust check
                stats["dealer_busts"] += 1

        # Check for the final result code (Win/Loss/Tie) 
        if res != 0:
            print(f"Dealer's Final Hand: {format_hand(dealer_hand)} (Total: {calculate_points(dealer_hand)})")
            status = {0x3: "WINNER! 🏆", 0x2: "LOSER... 💀", 0x1: "TIE 🤝"}.get(res, "Unknown")
            print(f"Round Result: {status}")
            return res

def safe_recv(sock):
    """Reliably receives 9-byte payload packets and validates the cookie."""
    try:
        data = sock.recv(9)
        if len(data) < 9: 
            raise ConnectionError("Server disconnected mid-round")
        
        # Unpack: Cookie(4), MsgType(1), Result(1), RankHigh(1), RankLow(1), Suit(1)
        cookie, msg_type, res, r_h, r_l, suit = struct.unpack('>IBB3B', data)
        
        if cookie != MAGIC_COOKIE:
            raise ValueError("Corrupted packet (Wrong Cookie)")
            
        return res, (r_h << 8) | r_l, suit
    except Exception as e:
        print(f"Error receiving data: {e}")
        return 0, 0, 0

def calculate_points(hand):
    """Calculates blackjack total where Ace=11 and Face=10."""
    total = 0
    for r, _ in hand:
        if r == 1: total += 11   # Ace
        elif r >= 11: total += 10 # Jack, Queen, King
        else: total += r          # 2-10
    return total

def format_hand(hand):
    """Converts a list of card tuples into a single pretty string."""
    return " ".join([get_card_str(r, s) for r, s in hand])

def display_stats(rounds, s):
    """Prints the final rock-themed summary."""
    duration = round(time.time() - s["start_time"], 1)
    win_rate = (s["wins"] / rounds) * 100
    
    print("\n" + "="*45)
    print("🎸 STRAIGHT SHOOTERS: SESSION SUMMARY 🎸")
    print("="*45)
    print(f"🏆 Win Rate: {win_rate:.2f}% ({s['wins']} wins / {rounds} rounds)")
    print(f"⏱️ Jam Time: {duration} seconds")
    print(f"🤝 Ties: {s['ties']} | 💀 Losses: {s['losses']}")
    print("-"*45)
    print(f"🃏 Aces Drawn: {s['aces_drawn']} (Ace of Spades!)")
    print(f"🔥 Total Hits: {s['total_hits']} (Motorhead Speed)")
    print(f"💥 Your Busts: {s['busts']} | 🃏 Dealer Busts: {s['dealer_busts']}")
    print(f"🎤 Rock Status: {'METALLICA LEVEL' if win_rate >= 50 else 'GARAGE BAND'}")
    print("="*45)

if __name__ == "__main__":
    start_client()