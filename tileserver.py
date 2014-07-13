# A PHP TileMap Server
#
# Serves image tiles, UTFgrid tiles and TileJson definitions
# from MBTiles files (as used by TileMill). (Partly) implements
# the Tile Map Services Specification.
#
# Originally based on https://github.com/Zverik/mbtiles-php,
# but refactored and extended.
#
# @author E. Akerboom (github@infostreams.net)
# @version 1.1
# @license LGPL

# TODO
#header('Access-Control-Allow-Origin: *');

import sqlite3, os, glob, textwrap, zlib, json, hashlib, time, cStringIO, sys
import posixpath, urllib, argparse
from wsgiref.handlers import format_date_time

from gevent import monkey
monkey.patch_all()
import bottle
from bottle import abort, response, request

from PIL import Image, ImageDraw

def htmlspecialchars(txt):
    return txt.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

app = bottle.Bottle()

def run():
    bottle.debug(True)

    parser = argparse.ArgumentParser(description='Tile server', formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--port', '-p', type=int, default=8080, help='port number')
    args = parser.parse_args()

    setup_routes(app)

    port = args.port
    try:
        import gevent
        app.run(host='127.0.0.1', port=port, server='gevent')
    except ImportError:
        print "WARNING: falling back to single threaded mode"
        app.run(host='127.0.0.1', port=port)

def setup_routes(app):

    idfn = lambda v: v
    def identifier_filter(config):
        regexp = r'[-_\d\w\s]+'
        return [regexp, idfn, idfn]
    app.router.add_filter('_identifier', identifier_filter)

    @app.route('/')
    def root():
        return ServerInfoController().hello()

    @app.route('/root.xml')
    def rootxml():
        return TileMapServiceController().root()

    @app.route('/1.0.0')
    def vsn():
        return TileMapServiceController().service()

    @app.route('/1.0.0/<layer:_identifier>')
    def vsnlayer(layer):
        return TileMapServiceController().resource(layer=layer)

    @app.route("/1.0.0/<layer:_identifier>/<z:int>/<x:int>/<y:int>.<ext:re:(png|jpg|jpeg|json)>")
    def servetmstile(layer, z, x, y, ext):
        return MapTileController().serveTmsTile(tileset=layer, x=x, y=y, z=z, ext=ext)

    @app.route("/<layer:_identifier>/<z:int>/<x:int>/<y:int>.<ext:re:(png|jpg|jpeg|json)>")
    def servetile1(layer, z, x, y, ext):
        return MapTileController().serveTile(layer=layer, x=x, y=y, z=z, ext=ext)

    @app.route("/<layer:_identifier>/<z:int>/<x:int>/<y:int>.<ext:re:(json|jsonp)>")
    def servetile2(layer, z, x, y, ext):
        callback = None
        if request.query != '':
            callback = request.query.values()[1]
        return MapTileController().serveTile(layer=layer, x=x, y=y, z=z, ext=ext, callback=callback)

    @app.route("/<layer:_identifier>/<z:int>/<x:int>/<y:int>.grid.<ext:re:(json|jsonp)>")
    def servetile3(layer, z, x, y, ext):
        callback = None
        if request.query != '':
            callback = request.query.values()[1]
        return MapTileController().serveTile(layer=layer, x=x, y=y, z=z, ext=ext, callback=callback)

    @app.route("/<layer:_identifier>.tile<:re:(json|jsonp)>")
    def tilejson(layer):
        callback = None
        if request.query.values():
            callback = request.query.values()[1]
        return MapTileController().tileJson(layer=layer, callback=callback)


class BaseClass(object):

    def __init__(self, *args, **kwargs):
        super(BaseClass, self).__init__(*args, **kwargs)
        self.layer = None
        self.db = None

    def getMBTilesName(self):
        return self.layer + ".mbtiles"

    def openDB(self):
        filename = self.getMBTilesName()

        if os.path.isfile(filename):
            self.db = sqlite3.connect(filename)
        else:
            abort(404, "Incorrect tileset name: " + self.layer)

    def closeDB(self):
        self.db.close()

class ServerInfoController(BaseClass):

    def __init__(self, *args, **kwargs):
        super(ServerInfoController, self).__init__(*args, **kwargs)

    def hello(self):

        ret = ''

        x = TileMapServiceController()
        ret += "This is the " + x.server_name + " version " + x.server_version

        ret += "<br /><br />Try these!"
        ret += "<ul>"
        for route in app.routes:
            if len(route.rule) > 1 and "<layer" not in route.rule:
                ret += "<li><a href='%s'>%s</a></li>" % (route.rule, route.rule)

        layers = glob.glob("*.mbtiles")
        for l in layers:
            l = l.replace(".mbtiles", "")
            urls = [l + u for u in ["/2/1/1.png", ".tilejson", "/2/1/1.json"]]
            for u in urls:
                ret += "<li><a href='%s'>%s</a></li>" % (u, u)
        ret += "</ul>"
        ret += "<br/><br/>PS: non-exhaustive list, see source for details"

        return ret

#
# Implements a TileMapService that returns XML information on the provided
# services.
#
# @see http://wiki.osgeo.org/wiki/Tile_Map_Service_Specification
# @author zverik (https://github.com/Zverik)
# @author E. Akerboom (github@infostreams.net)
#
class TileMapServiceController(BaseClass):

    def __init__(self, *args, **kwargs):
        super(TileMapServiceController, self).__init__(*args, **kwargs)
        self.server_name = "Python TileMap server"
        self.server_version = "1.0.0"

    def root(self):
        base = self.getBaseUrl()

        response.set_header('Content-type', 'text/xml')
        return textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8" ?>
            <Services>
                <TileMapService title="%s" version="%s" href="%s%s/" />
            </Services>""" % (
                self.server_name, self.server_version, base, self.server_version
            ))

    def service(self):
        base = self.getBaseUrl()

        response.set_header('Content-type', 'text/xml')
        ret = ''
        ret += "<?xml version=\"1.0\" encoding=\"UTF-8\" ?>"
        ret += "\n<TileMapService version=\"1.0.0\" services=\"%s\">" % (base,)
        ret += "\n\t<Title>%s v%s</Title>" % (self.server_name, self.server_version)
        ret += "\n\t<Abstract />"

        ret += "\n\t<TileMaps>"

        for dbfile in glob.glob('*.mbtiles'):
            if not os.path.isfile(dbfile):
                continue
            try:
                db = sqlite3.connect(dbfile)
                params = self.readparams(db)
                name = htmlspecialchars(params['name'])
                identifier = dbfile.replace('.mbtiles', '')
                ret += ('\n\t\t<TileMap title="%s" srs="OSGEO:41001" ' +
                    'profile="global-mercator" href="%s1.0.0/%s" />'
                    ) % (name, base, identifier)
            except sqlite3.DatabaseError:
                pass

        ret += "\n\t</TileMaps>"
        ret += "\n</TileMapService>"
        return ret

    def resource(self, layer):
        ret = ''
        try:
            self.layer = layer
            self.openDB()
            params = self.readparams(self.db)

            title = htmlspecialchars(params['name'])
            description = htmlspecialchars(params['description'])
            if 'format' in params and params['format'].lower() in ["jpg", "jpeg"]:
                fmt = params['format'].lower()
                mimetype = "image/jpeg"
            else:
                fmt = "png"
                mimetype = "image/png"

            base = self.getBaseUrl()
            response.set_header('Content-type', 'text/xml')
            ret += textwrap.dedent("""\
                <?xml version="1.0" encoding="UTF-8" ?>
                <TileMap version="1.0.0" tilemapservice="%s1.0.0/">
                \t<Title>%s</Title>
                \t<Abstract>%s</Abstract>
                \t<SRS>OSGEO:41001</SRS>
                \t<BoundingBox minx="-180" miny="-90" maxx="180" maxy="90" />
                \t<Origin x="0" y="0"/>
                \t<TileFormat width="256" height="256" mime-type="%s" extension="%s"/>
                \t<TileSets profile="global-mercator">
                """ % (base, title, description, mimetype, fmt)
            )

            minzoom = int(params['minzoom'])
            maxzoom = int(params['maxzoom'])
            for zoom in range(minzoom, maxzoom + 1):
                href = base + "1.0.0/" + self.layer + "/" + str(zoom)
                units_pp = 78271.516 / pow(2, zoom)
                ret += '<TileSet href="%s" units-per-pixel="%s" order="%s" />' % (
                    href, units_pp, zoom
                )
            ret += textwrap.dedent("""\t</TileSets>\n</TileMap>""")
        except sqlite3.DatabaseError:
            abort(404, "Incorrect tileset name: " + self.layer)

        return ret

    def readparams(self, db):
        params = {}
        cur = db.cursor()
        cur.execute('select name, value from metadata')
        result = cur.fetchall()
        for name, value in result:
            params[name] = value
        return params

    def getBaseUrl(self):
        parts = request.urlparts
        return parts.scheme + "://" + parts.netloc + '/'


class MapTileController(BaseClass):

    def __init__(self, *args, **kwargs):
        super(MapTileController, self).__init__(*args, **kwargs)
        self.x = None
        self.y = None
        self.z = None
        self.tileset = None
        self.ext = None
        self.callback = None

        self.is_tms = False

    def set(self, layer, x, y, z, ext, callback):
        self.layer = layer
        self.x = x
        self.y = y
        self.z = z
        self.ext = ext
        self.callback = callback

    def serveTile(self, layer, x, y, z, ext, callback=None):
        self.set(layer, x, y, z, ext, callback)

        if not self.is_tms:
            self.y = pow(2, self.z) - 1 - self.y

        if self.ext.lower() in ["json", "jsonp"]:
            if self.callback is None:
                return self.jsonTile()
            else:
                return self.jsonpTile()
        elif self.ext.lower() in ["png", "jpeg", "jpg"]:
            return self.imageTile()
        else:
            abort(404, "Tile type not found")

    def serveTmsTile(self, tileset, x, y, z, ext, callback=None):
        self.is_tms = True
        return self.serveTile(tileset + "-tms", x, y, z, ext, callback)

    def jsonTile(self):
        etag = self.etag("json")
        self.checkCache(etag)

        jsongrid = self.getUTFgrid()

        # serve JSON file
        response.set_header('Content-type', 'application/json; charset=utf-8')
        response.set_header('Content-Length', len(jsongrid))
        self.cachingHeaders(etag)

        return jsongrid

    def jsonpTile(self):
        etag = self.etag("jsonp")
        self.checkCache(etag)

        jsongrid = self.getUTFgrid()
        jsonpgrid = self.callback + "(" + jsongrid + ")"

        # serve JSON file
        response.set_header('Content-type', 'application/json; charset=utf-8')
        response.set_header('Content-Length', len(jsonpgrid))
        self.cachingHeaders(etag)

        return jsonpgrid

    def etag(self, etag_type):
        return '"' + hashlib.sha1(
            "%s-%s-%s-%s-%s-%s" % (
                self.tileset, self.x, self.y, self.z,
                etag_type, os.path.getmtime(self.getMBTilesName())
            )
        ).hexdigest() + '"'

    def checkCache(self, etag):
        if 'If-None-Match' in request.headers and request.headers['If-None-Match'] == etag:
            abort(304, 'Not Modified')

    def cachingHeaders(self, etag=None):
        day = 60*60*24
        expires_secs = 1 * day
        expires = format_date_time(time.time() + expires_secs)

        # For an explanation on how the expires header and the etag header work
        # together, please see http://stackoverflow.com/a/500103/426224
        response.set_header("Expires", expires)
        response.set_header("Pragma", "cache")
        response.set_header("Cache-Control", "public, max-age=" + str(expires_secs))
        if etag is not None:
            response.set_header('ETag', etag)

    def imageTile(self):
        etag = self.etag("img")
        self.checkCache(etag)

        if self.is_tms:
            self.tileset = self.tileset[:len(self.tileset) - 4]

        try:
            self.openDB()

            cur = self.db.cursor()
            cur.execute('select tile_data as t from tiles where zoom_level=? and tile_column=? and tile_row=?', (self.z, self.x, self.y))
            data = cur.fetchone()

            if not data:

                # did not find a tile - return an empty (transparent) tile
                img = Image.new('RGBA', (256, 256))
                draw = ImageDraw.Draw(img)
                draw.rectangle([0, 0, 256, 256], fill=(0, 0, 0, 0))
                imgfile = cStringIO.StringIO()
                img.save(imgfile, 'png')
                data = imgfile.getvalue()
                imgfile.close()
                response.set_header('Content-type', 'image/png')
                self.cachingHeaders(etag)

            else:

                # Hooray, found a tile!
                # - figure out which format (jpeg or png) it is in
                data = data[0]
                cur.execute('select value from metadata where name="format"')
                result = cur.fetchone()
                if result:
                    fmt = result[0]
                else:
                    fmt = 'png'
                if fmt == 'jpg':
                    fmt = 'jpeg'

                # - serve the tile
                response.set_header('Content-type', 'image/' + fmt)
                self.cachingHeaders(etag)

            self.closeDB()
            return data

        except sqlite3.DatabaseError as e:
            self.closeDB()
            abort(500, 'Error querying the database: ' + e.message)

    def getUTFgrid(self):
        self.openDB()

        try:
            flip = True
            if self.is_tms:
                self.tileset = self.tileset[:len(self.tileset) - 4]
                flip = False

            cur = self.db.cursor()
            cur.execute('select grid as g from grids where zoom_level=? and tile_column=? and tile_row=?', (self.z, self.x, self.y))
            data = cur.fetchone()

            if not data:
                # nothing found - return empty JSON object
                return "{}"
            else:
                data = data[0]
                # get the gzipped json from the database
                grid = zlib.decompress(data[0])

                # manually add the data for the interactivity layer by means of string manipulation
                # to prevent a bunch of costly calls to json_encode & json_decode
                #
                # first, strip off the last '}' character
                grid = grid.strip()[:-1]
                # then, add a new key labelled 'data'
                grid += ',"data":{'

                # stuff that key with the actual data
                cur = self.db.cursor()
                cur.execute('select key_name as key, key_json as json from grid_data where zoom_level=? and tile_column=? and tile_row=?', (self.z, self.x, self.y))
                result = cur.fetchall()
                for row in result:
                    grid += '"' + row[0] + '":' + row[1] + ','

                # finish up
                grid = grid.rstrip(',') + "}}"

                # done
                return grid
        except sqlite3.DatabaseError as e:
            self.closeDB()
            abort(500, 'Error querying the database: ' + e.message)

    def tileJson(self, layer, callback):
        self.layer = layer
        self.openDB()
        try:
            tilejson = {}
            tilejson['tilejson'] = "2.0.0"
            tilejson['scheme'] = "xyz"

            cur = self.db.cursor()
            cur.execute('select name, value from metadata')
            result = cur.fetchall()
            for row in result:
                key = row[0]
                value = row[1]
                if key in ['maxzoom', 'minzoom']:
                    value = int(value)
                tilejson[key] = value

            if 'bounds' in tilejson:
                tilejson['bounds'] = [float(b) for b in tilejson['bounds'].split(',')]
            if 'center' in tilejson:
                tilejson['center'] = [float(c) for c in tilejson['center'].split(',')]

            ## find out the absolute URL to this script
            parts = request.urlparts
            server_url = parts.scheme + "://" + parts.netloc + posixpath.dirname(parts.path)
            url_layer = urllib.quote(layer)

            tilejson['webpage'] = server_url
            tilejson['tiles'] = [server_url + url_layer + "/{z}/{x}/{y}.png"]
            tilejson['grids'] = [server_url + url_layer + "/{z}/{x}/{y}.json"]

            if callback is not None:
                ret = callback + "(" + json.dumps(tilejson) + ")"
            else:
                ret = json.dumps(tilejson)

            response.set_header('Content-type', 'application/json')
            response.set_header('Content-Length', len(ret))
            self.cachingHeaders()

            return ret

        except sqlite3.DatabaseError as e:
            self.closeDB()
            abort(500, 'Error querying the database: ' + e.message)

if __name__ == '__main__':
    run()
