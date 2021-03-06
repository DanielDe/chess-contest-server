from twisted.web.resource import Resource
from twisted.web.resource import NoResource
from twisted.web.static import File
from twisted.web.util import redirectTo

from tournament_list import TournamentList

class HttpRoot(Resource):
    def __init__(self, manager):
        self.children = []
        self.manager = manager

    def getChild(self, name, request):
        if name == '':
            return self
        elif name == 'static':
            return File('./static/')
        elif name == 'tournaments':
            return TournamentList(self.manager)
        else:
            return NoResource()

    def render_GET(self, request):
        return redirectTo("/tournaments", request)
