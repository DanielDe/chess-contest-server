from twisted.web.resource import Resource
from twisted.web.resource import NoResource
from twisted.web.static import File
from game_resource import GameResource
from human_client import HumanClient

import urllib
import cgi
import datetime

class Tournament(Resource):
    def __init__(self, manager, tournament):
        self.manager = manager
        self.tournament = tournament
        self.children = []

    def getChild(self, name, request):
        if name == '':
            return self
        elif name == 'play':
            return HumanClient(self.tournament)
        else:
            if not name in self.tournament.games:
                return NoResource("No game with id %s found" % name)
            return GameResource(self.tournament.games[name])

    def details_table(self):
        created_date = datetime.datetime.fromtimestamp(self.tournament.created_at).strftime('%Y-%m-%d %H:%M:%S')
        rtn  = "<table border=\"1\">"
        rtn += "<tr><td><b>Created</b></td><td>%s</td></tr>" % created_date
        rtn += "<tr><td><b>Time limit</b></td><td>%s</td></tr>" % self.tournament.time_limit
        rtn += "<tr><td><b>Increment</b></td><td>%s</td></tr>" % self.tournament.increment
        rtn += "<tr><td><b>Games per pairing</b></td><td>%s</td></tr>" % self.tournament.games_per_pair
        rtn += "</table>"
        return rtn

    def standings_table(self):
        standings = self.tournament.get_standings()
        if len(standings) == 0:
            return "<p>No players</p>"
        rtn = "<table border=\"1\"><tr><td><b>Player</b></td><td><b>Games Played</b></td><td><b>Points</b></td></tr>"
        for pname in standings:
            rtn += "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (cgi.escape(pname).encode("utf-8"), standings[pname]['played'], standings[pname]['score'])
        rtn += "</table>"
        return rtn

    def game_list(self, games):
        if len(games) == 0:
            return "<p>No games</p>"
        games = sorted(games, key=lambda g:g.created_at, reverse=True)

        rtn = "<ul>"
        for g in games:
            l = "<a href=\"/tournaments/%s/%s\">%s v. %s</a>" % (urllib.quote(self.tournament.name.encode("utf-8"), safe=""), g.id, cgi.escape(g.players[0].name).encode("utf-8"), cgi.escape(g.players[1].name).encode("utf-8"))
            if g.status != "*":
                l += " %s-%s %s" % (g.outcomes[0], g.outcomes[1], g.status)
            rtn += "<li>%s</li>" % (l,)
        rtn += "</ul>"
        return rtn

    def render_GET(self, request):
        request.setHeader("Content-Type", "text/html; charset=utf-8")

        html = "<html><head><h1>Tournament %s</h1></head><body>" % (cgi.escape(self.tournament.name).encode("utf-8"),)
        html += "<p>Details</p>"
        html += self.details_table()

        html += "<h3><a href=\"/tournaments/%s/play\">Join Tournament</a></32>" % (urllib.quote(self.tournament.name.encode("utf-8"), safe=''),)

        html += "<h2>Standings</h2>"
        html += self.standings_table()
        html += "<h2>Active Games</h2>"
        html += self.game_list(self.tournament.active_games())
        html += "<h2>Completed Games</h2>"
        html += self.game_list(self.tournament.compleated_games())
        html += "</body></html>"
        return html






