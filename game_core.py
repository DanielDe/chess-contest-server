import chess
import chess.pgn

import random
import time
import uuid
import logging

class PlayerState:
    CONNECTING          = 0
    WAITING_PAIRING     = 1
    IN_GAME_NEEDS_ACK   = 2
    IN_GAME_ACKED       = 3
    PLAYING             = 4

class GameState:
    NEEDS_ACK    = 0
    IN_PROGRESS  = 1
    FINISHED     = 2
    ABORTED      = 3

#base class for various types of connections to the server
class BasePlayer(object):
    def __init__(self):
        self.name = None
        self.tournament_name = None
        self.state = PlayerState.CONNECTING
        self.current_game = None
        self.observing_games = []

    def format_message(self, action, message):
        if len(message):
            return "%s %s\n" % (action.upper(), message)
        else:
            return "%s\n" % (action.upper(),)

    def parse_message(self, input):
        if " " in input:
            action, message = input.split(" ", 1)
        else:
            action, message = input, ""
        return action.upper(), message.strip()


    def send_message(self, action, message):
        raise Exception("Not Implemented")

    def force_disconnect(self):
        raise Exception("Not Implemented")


class Manager(object):
    def __init__(self):
        self.tournaments = {}

    def create_tournament(self, tournament_name, games_per_pair, time_limit, increment):
        tournament_name = tournament_name.strip()
        assert all ((c.isalnum() or c in "_-!") for c in tournament_name), "Bad character in tournament name"
        assert not tournament_name in self.tournaments, "Tournament of name %s already exists" % (tournament_name,)
        self.tournaments[tournament_name] = Tournament(tournament_name, games_per_pair, time_limit, increment)

    def player_connected(self, player):
        player.state = PlayerState.CONNECTING

    def player_disconnected(self, player):
        if player.tournament_name in self.tournaments:
            tournament = self.tournaments[player.tournament_name]
            tournament.remove_player(player)

        for game in player.observing_games[:]:
            game.remove_observer(player)


    def game_for_id(self, game_id):
        for t in self.tournaments.values():
            g = t.game_for_id(game_id)
            if g:
                return g
        return False

    def message_recieved(self, player, action, message):
        parts = [s for s in message.split(" ") if len(s)]

        if action == "DISCONNECT":
            player.force_disconnect()
            return
        elif action == "WATCH" or action == "UNWATCH":
            assert len(parts) == 1, "Bad game id"
            game = self.game_for_id(parts[0])
            assert game, "No game found with id %s" % (parts[0],)
            if action == "WATCH":
                game.add_observer(player)
            else:
                game.remove_observer(player)
            return

        if player.state == PlayerState.CONNECTING:
            assert action == "JOIN", "First message must be a JOIN or WATCH"
            assert len(parts) == 2, "Bad name or tournament"
            tournament_name = parts[0]
            player.name = parts[1]
            assert tournament_name in self.tournaments , "Tournament %s not found" % (tournament_name,)
            self.tournaments[tournament_name].add_player(player)
            player.state = PlayerState.WAITING_PAIRING
        else:
            assert player.tournament_name != None and self.tournaments.get(player.tournament_name)
            tournament = self.tournaments[player.tournament_name]
            tournament.message_recieved(player, action, message)


    def update_pairings(self):
        for t in self.tournaments.values():
            t.update_pairings()

    def check_timeouts(self):
        for t in self.tournaments.values():
            t.check_timeouts()

    def send_clock_updates(self):
        for t in self.tournaments.values():
            t.send_clock_updates()


class Tournament(object):
    def __init__(self, name, games_per_pair, time_limit, increment):
        self.name = name
        self.games_per_pair = games_per_pair
        self.time_limit = time_limit
        self.increment = increment
        self.players = {}
        self.games = {}
        self.created_at = time.time()

    def message_recieved(self, player, action, message):
        assert len(message), "No game id provided"
        gameid = message.strip().split(" ")[0]

        if  gameid != player.current_game.id:
            m = "Game id in message (%s) does not match id of active game (%s)" % (gameid, player.current_game.id)
            if player.state in [PlayerState.IN_GAME_NEEDS_ACK, PlayerState.WAITING_PAIRING]:
                player.send_message("INFO", "Ignoring message of type %s. %s" % (action, m))
                return
            else:
                assert False, m

        player.current_game.message_recieved(player, action, message)

    def add_player(self, player):
        assert not player.name in self.players, "Player with name %s already in tournament" % (player.name,)

        m = "Player %s joined tournament (%s active players)" % (player.name, len(self.players) + 1)
        logging.info(m)
        for p in self.players.values():
            p.send_message("INFO", m)

        player.tournament_name = self.name
        self.players[player.name] = player


    def remove_player(self, player):
        if player.name in self.players:
            del self.players[player.name]

        m = "Player %s left tournament (%s active players)" % (player.name, len(self.players))
        logging.info(m)
        for p in self.players.values():
            p.send_message("INFO", m)

        if player.current_game:
            player.current_game.player_disconnected(player)

    def check_timeouts(self):
        for game in self.games.values():
            if game.state in [GameState.NEEDS_ACK, GameState.IN_PROGRESS]:
                game.check_timeout()

    def get_pairing_count(self, player1, player2):
        finished = [g for g in self.games.values() if g.state == GameState.FINISHED]
        return len([g for g in finished if g.players[0].name == player1.name and g.players[1].name == player2.name])


    def update_pairings(self):
        free_players = [p for p in self.players.values() if p.state == PlayerState.WAITING_PAIRING]
        random.shuffle(free_players)
        for i, p1 in enumerate(free_players):
            for p2 in free_players[i+1:]:
                if p1.state == PlayerState.WAITING_PAIRING and p2.state == PlayerState.WAITING_PAIRING:

                    wb = self.get_pairing_count(p1, p2)
                    bw = self.get_pairing_count(p2, p1)

                    if wb+bw < self.games_per_pair:
                        if wb < bw:
                            self.start_game(p1, p2)
                        else:
                            self.start_game(p2, p1)

    def send_clock_updates(self):
        for game in self.games.values():
            if game.state  == GameState.IN_PROGRESS:
                game.send_clock_updates()

    def start_game(self, white_player, black_player):
        game = Game(white_player, black_player, self.time_limit, self.increment)
        game.pgn.headers['Event']  = self.name
        self.games[game.id] = game
        white_player.current_game = game
        black_player.current_game = game
        white_player.state = PlayerState.IN_GAME_NEEDS_ACK
        black_player.state = PlayerState.IN_GAME_NEEDS_ACK
        game.send_game_started_message()
        logging.info("Starting game between %s and %s with id %s" % (white_player.name, black_player.name, game.id))

    def get_standings(self):
        standings = {}
        for p in self.players:
            standings[p] = {"played" : 0, "score" : 0}

        for game in self.games.values():
            if game.state == GameState.FINISHED:
                for i,p in enumerate(game.players):
                    standings[p.name] = standings.get(p.name, {"played" : 0, "score" : 0})
                    standings[p.name]["played"] += 1
                    standings[p.name]["score"] += game.outcomes[i]

        return standings

    def game_for_id(self, game_id):
        if game_id in self.games:
            return self.games[game_id]
        return None

    def compleated_games(self):
        return [g for g in self.games.values() if g.state == GameState.FINISHED]

    def active_games(self):
        return [g for g in self.games.values() if g.state == GameState.IN_PROGRESS]

    def all_games(self):
        return self.compleated_games() + self.active_games()



class Game(object):
    def __init__(self, white_player, black_player, time_limit, increment):
        self.time_limit = time_limit
        self.increment = increment
        self.times = [float(time_limit), float(time_limit)]
        self.players = [white_player, black_player]
        self.outcomes = [0, 0]
        self.status = "*"

        self.cur_move_started_at = 0.0
        self.cur_index = 0

        self.id = uuid.uuid1().hex

        self.state = GameState.NEEDS_ACK
        self.created_at = time.time()

        self.board = chess.Board()
        self.pgn = chess.pgn.Game()
        self.pgn.setup(self.board)
        self.pgn.headers.clear()
        self.pgn.headers['Result'] = "*"
        self.pgn.headers['White']  = white_player.name
        self.pgn.headers['Black']  = black_player.name

        self.pgn_node = self.pgn

        self.observers = []

    def other_player(self, player):
        if player == self.players[0]:
            return self.players[1]
        return self.players[0]

    def current_player(self):
        return self.players[self.cur_index]

    def next_player(self):
        return self.players[(self.cur_index + 1)%2]

    def send_all(self, action, message):
        for p in self.players:
            p.send_message(action, message)

        for o in self.observers:
            o.send_message(action, message)

    def message_recieved(self, player, action, message):
        if player.state == PlayerState.IN_GAME_NEEDS_ACK:
            if action == "ACK":
                self.player_acknowledged(player)
            else:
                player.send_message("INFO", "ignoring message type %s while waiting for ack" % (action))

        elif player.state == PlayerState.PLAYING:
            if action == "RESIGN":
                self.resign(player)
            elif action == "MOVE":
                assert " " in message
                _, move = message.split(" ", 1)
                self.make_move(player, move.strip())
            else:
                player.send_message("INFO", "ignoring message type %s." % (action))

    def check_timeout(self):
        if self.state == GameState.NEEDS_ACK:
            if time.time() - self.created_at > 20:
                logging.info("Game %s timed out before ack. Aborting..." % self.id)
                self.abort("Not acked by both players within time limit")
                return False
        elif self.state == GameState.IN_PROGRESS:
            thinking_time = time.time() - self.cur_move_started_at
            if self.times[self.cur_index] <= thinking_time:
                # thinking player is out of time!
                self.times = self.updated_times()
                self.cur_move_started_at = time.time()
                self.send_clock_updates()

                self.outcomes[self.cur_index] = 0
                self.outcomes[(self.cur_index + 1)%2] = 1
                self.status = "Out of time"
                self.game_over()
                return False
        return True

    def outcome_str(self):
        if self.state != GameState.FINISHED:
            return ""
        return "Game over: %s-%s %s" % (self.outcomes[0], self.outcomes[1], self.status)

    def game_state_str(self):
        times = self.updated_times()
        return "%s %s %s %0.2f %0.2f %s" % (self.id, self.players[0].name, self.players[1].name, times[0], times[1], self.board.fen())

    def send_clock_updates(self):
        self.send_all("CLOCK_UPDATE", self.game_state_str())


    def abort(self, reason):
        self.state = GameState.ABORTED
        self.status = "Game aborted"

        self.send_all("GAME_ABORTED", reason)
        for p in self.players:
            p.current_game = None
            p.state = PlayerState.WAITING_PAIRING

    def resign(self, player):
        i = self.players.index(player)
        self.outcomes[i] = 0
        self.outcomes[(i + 1)%2] = 1
        self.status = "Resignation"
        self.game_over()

    def send_game_started_message(self):
        self.send_all("GAME_STARTED", self.game_state_str())

    def player_disconnected(self, player):
        if player == self.players[0]:
            self.outcomes = [0, 1]
        else:
            self.outcomes = [1, 0]

        self.status = "Resignation by disconnect"
        self.game_over()

    def add_observer(self, observer):
        logging.info("Adding observer to game %s" % (self.id,))
        times = self.updated_times()
        observer.send_message("GAME_STATE", self.game_state_str())
        self.observers.append(observer)
        observer.observing_games.append(self)

    def remove_observer(self, observer):
        logging.info("Removing observer from game %s" % (self.id,))

        if observer in self.observers:
            self.observers.remove(observer)
        if self in observer.observing_games:
            observer.observing_games.remove(self)

    def game_over(self):
        self.state = GameState.FINISHED
        #send message
        message = "%s %s-%s %s" % (self.id, self.outcomes[0], self.outcomes[1], self.status)

        self.send_all("GAME_OVER", message)
        for p in self.players:
            p.current_game = None
            p.state = PlayerState.WAITING_PAIRING


    def player_acknowledged(self, player):
        player.state = PlayerState.IN_GAME_ACKED
        if all (p.state == PlayerState.IN_GAME_ACKED for p in self.players):
            self.send_all("INFO", "Both players have acknowledged game. Starting...")
            self.send_all("GAME_ACKED", "")

            for p in self.players:
                p.state = PlayerState.PLAYING

            self.state = GameState.IN_PROGRESS

            self.cur_move_started_at = time.time()
            self.get_move_from_current_player()
        else:
            player.send_message("INFO", "Waiting for opponent to acknowledged game")


    # game times updated for how long the current player has been thinking
    def updated_times(self):
        times = self.times[:]
        if self.state != GameState.IN_PROGRESS:
            return times
        times[self.cur_index] -= (time.time() - self.cur_move_started_at)
        times[self.cur_index] = max(times[self.cur_index], 0)
        return times

    def get_move_from_current_player(self):
        player = self.players[self.cur_index]
        times = self.updated_times()

        player.send_message("YOUR_MOVE", "%s %s %s %s" % (self.id, times[0], times[1], self.board.fen()))

    def clean_move(self, player, move):
        move = move.strip()
        if move.upper() in ["O-O", "0-0"]:
            if (player == self.players[0]):
                return "e1-g1"
            else:
                return "e8-g8"
        elif move.upper() in ["O-O-O", "0-0-0"]:
            if (player == self.players[0]):
                return "e1-c1"
            else:
                return "e8-c8"

        move[:-2].lower()
        if move[-2] == "=":
            move = move[:-2] + move[-2:].upper()

        return move

    def is_draw(self):
        if self.board.is_stalemate():
            return True, "Stalemate"
        if self.board.is_insufficient_material():
            return True, "Insufficient material"
        if self.board.can_claim_threefold_repetition():
            return True, "Threefold repetition"
        if self.board.can_claim_fifty_moves():
            return True, "Fifty moves without capture or pawn push"
        return False, ""


    def make_move(self, player, move):
        if player != self.current_player():
            player.send_message("INFO", "Ignoring message. It's not your move")
            return

        if not self.check_timeout():
            #game is over by timeout!
            return

        clean_move = self.clean_move(player, move)
        uci_move = "".join(clean_move.split("-"))
        engine_move = chess.Move.from_uci(uci_move)
        if not engine_move in self.board.legal_moves:
            player.send_message("INFO", "Move %s is not legal" % (move,))
            self.get_move_from_current_player()
            return
        else:
            self.board.push(engine_move)
            self.pgn_node = self.pgn_node.add_variation(engine_move)

        self.times = self.updated_times()
        self.cur_move_started_at = time.time()
        self.times[self.cur_index] += self.increment



        message = "%s %s %s %s" % (self.id, self.current_player().name, clean_move, " ".join(self.game_state_str().split(" ")[1:]))
        self.send_all("PLAYER_MOVED", message)

        if self.board.is_checkmate():
            logging.info("Checkmate on game %s!" % (self.id))
            self.outcomes[self.cur_index] = 1
            self.status = "Checkmate"
            self.game_over();
            return;

        draw, reason = self.is_draw()
        if draw:
            logging.info("Draw on game %s: " % (self.id, reason))
            self.outcomes = [0.5, 0.5]
            self.status = reason
            self.game_over();
            return;

        self.cur_index = (self.cur_index + 1) % 2
        self.get_move_from_current_player()




