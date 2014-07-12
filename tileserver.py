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

import bottle
from bottle import abort, response, request

import sqlite3, os, glob, textwrap, zlib, json
from PIL import Image, ImageDraw
json_encode = json.dumps

app = bottle.Bottle()

identity = lambda x: x
def identifier_filter(config):
    regexp = r'[-\d_\s]+'
    def to_python(val):
        return val
    def to_url(val):
        return val
    return regexp, to_python, to_url
def number_filter(config):
    regexp = r'\d+'
    def to_python(val):
        return val
    def to_url(val):
        return val
    return regexp, to_python, to_url
app.router.add_filter('_identifier', identifier_filter)
app.router.add_filter('_number', number_filter)

def htmlspecialchars(txt):
    return txt.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")

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

@app.route("1.0.0/<layer:_identifier>/<z:_number>/<x:_number>/<y:_number>.<ext:re:(png|jpg|jpeg|json)>")
def servetmstile(layer, z, x, y, ext):
    return MapTileController().serveTmsTile(tileset=layer, x=x, y=y, z=z, ext=ext)

@app.route("<layer:_identifier>/<z:_number>/<x:_number>/<y:_number>.<ext:re:(png|jpg|jpeg|json)>")
def servetile1(layer, z, x, y, ext):
    return MapTileController().serveTile(layer=layer, x=x, y=y, z=z, ext=ext)

@app.route("<layer:_identifier>/<z:_number>/<x:_number>/<y:_number>.<ext:re:(json|jsonp)>")
def servetile2(layer, z, x, y, ext):
    callback = None
    if request.query != '':
        callback = request.query.split('=')[1]
    return MapTileController().serveTile(layer=layer, x=x, y=y, z=z, ext=ext, callback=callback)

@app.route("<layer:_identifier>/<z:_number>/<x:_number>/<y:_number>.grid.<ext:re:(json|jsonp)>")
def servetile3(layer, z, x, y, ext):
    callback = None
    if request.query != '':
        callback = request.query.split('=')[1]
    return MapTileController().serveTile(layer=layer, x=x, y=y, z=z, ext=ext, callback=callback)

@app.route("<layer:_identifier>.tile<:re:(json|jsonp)>")
def tilejson(layer):
    callback = None
    if request.query != '':
        callback = request.query.split('=')[1]
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

        # TODO
        #$x = new TileMapServiceController();
        #echo "This is the " . $x->server_name . " version " . $x->server_version;

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
            fmt = params['format']

            if fmt.lower in ["jpg", "jpeg"]:
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

            for zoom in self.readzooms(self.db):
                href = base + "1.0.0/" + self.layer + "/" + zoom
                units_pp = 78271.516 / pow(2, zoom)

                ret += '<TileSet href="%s" units-per-pixel="%s" order="%s" />' % (href, units_pp, zoom)
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

    def readzooms(self, db):
        params = self.readparams(db)
        minzoom = params['minzoom']
        maxzoom = params['maxzoom']
        return range(minzoom, maxzoom + 1)

    def getBaseUrl(self):
        return "http://localhost:8080/"
        # TODO
        #$protocol = empty($_SERVER["HTTPS"])?"http":"https";
        #return $protocol . '://' . $_SERVER['HTTP_HOST'] . preg_replace('/\/(1.0.0\/)?[^\/]*$/', '/', $_SERVER['REQUEST_URI']);



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
        # TODO
        #etag = self.etag("json");
        #self.checkCache(etag);

        json = self.getUTFgrid()

        # TODO
        # disable ZLIB ouput compression
        #ini_set('zlib.output_compression', 'Off');

        # serve JSON file
        response.set_header('Content-type', 'application/json; charset=utf-8')
        response.set_header('Content-Length', len(json))
        # TODO
        #self.cachingHeaders(etag);

        return json;

    def jsonpTile(self):
        # TODO
        #$etag = self.etag("jsonp");
        #self.checkCache($etag);

        json = self.getUTFgrid()
        jsonp = self.callback + "(" + json + ")"

        # TODO
        # disable ZLIB output compression
        #ini_set('zlib.output_compression', 'Off');

        # serve JSON file
        response.set_header('Content-type', 'application/json; charset=utf-8')
        response.set_header('Content-Length', len(json))
        # TODO
        #self.cachingHeaders(etag);

        return jsonp

    # TODO
    #def etag($type):
    #    return sha1(sprintf("%s-%s-%s-%s-%s-%s", self.tileset, self.x, self.y, self.z, $type, filemtime(self.getMBTilesName())));
    #}

    # TODO
    #def checkCache($etag):
    #    if (isset($_SERVER['HTTP_IF_NONE_MATCH']) && $_SERVER['HTTP_IF_NONE_MATCH'] == $etag) {
    #        header('HTTP/1.1 304 Not Modified');
    #        exit();
    #    }
    #}

    # TODO
    #def cachingHeaders($etag=null):
    #    $day = 60*60*24;
    #    $expires = 1 * $day;

    #    // For an explanation on how the expires header and the etag header work together,
    #    // please see http://stackoverflow.com/a/500103/426224
    #    header("Expires: " . gmdate('D, d M Y H:i:s', time()+$expires));
    #    header("Pragma: cache");
    #    header("Cache-Control: max-age=$expires");
    #    if (is_string($etag)) {
    #        header("ETag: {$etag}");
    #    }
    #}

    def imageTile(self):
        # TODO
        #$etag = self.etag("img");
        #self.checkCache($etag);

        if self.is_tms:
            self.tileset = self.tileset[:len(self.tileset) - 4]

        try:
            self.openDB()

            cur = self.db.cursor()
            cur.execute('select tile_data as t from tiles where zoom_level=' + self.z + ' and tile_column=' + self.x + ' and tile_row=' + self.y)
            data = cur.fetchone()

            if not data:

                # did not find a tile - return an empty (transparent) tile
                # TODO properly
                img = Image.new('RGBA',(256, 256))
                draw = ImageDraw.Draw(img)
                draw.rectangle([0, 0, 256, 256], fill=(0, 0, 0, 127))
                data = img.tobytes('PNG')
                #$png = imagecreatetruecolor(256, 256);
                #imagesavealpha($png, true);
                #$trans_colour = imagecolorallocatealpha($png, 0, 0, 0, 127);
                #imagefill($png, 0, 0, $trans_colour);
                #imagepng($png);

                response.set_header('Content-type', 'image/png')
                # TODO
                #self.cachingHeaders($etag);

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
                # TODO
                #self.cachingHeaders($etag);

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
            cur.execute('select grid as g from grids where zoom_level=' + self.z + ' and tile_column=' + self.x + ' and tile_row=' + self.y)
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
                cur.execute('select key_name as key, key_json as json from grid_data where zoom_level=' + self.z + ' and tile_column=' + self.x + ' and tile_row=' + self.y)
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

            # TODO
            ## find out the absolute URL to this script
            #$protocol = empty($_SERVER["HTTPS"])?"http":"https";
            #$server_url = $protocol . "://" . $_SERVER["HTTP_HOST"] . dirname($_SERVER["REQUEST_URI"]);

            #$tilejson['tiles'] = array(
            #    $server_url . "/" . urlencode($layer) . "/{z}/{x}/{y}.png"
            #);
            #$tilejson['grids'] = array(
            #    $server_url . "/" . urlencode($layer) . "/{z}/{x}/{y}.json"
            #);

            if callback is not None:
                json = callback + "(" + json_encode(tilejson) + ")"
            else:
                json = json_encode(tilejson)

            # TODO
            #ini_set('zlib.output_compression', 'Off')
            response.set_header('Content-type', 'application/json')
            response.set_header('Content-Length', len(json))
            # TODO
            #self.cachingHeaders();

            return json

        except sqlite3.DatabaseError as e:
            self.closeDB()
            abort(500, 'Error querying the database: ' + e.message)

app.run()

#
#
#/**
# * Rails like routing for PHP
# *
# * Based on http://blog.sosedoff.com/2009/09/20/rails-like-php-url-router/
# * but extended in significant ways:
# *
# * 1. Can now be deployed in a subdirectory, not just the domain root
# * 2. Will now call the indicated controller & action. Named arguments are
# *    converted to similarly method arguments, i.e. if you specify :id in the
# *    URL mapping, the value of that parameter will be provided to the method's
# *    '$id' parameter, if present.
# * 3. Will now allow URL mappings that contain a '?' - useful for mapping JSONP urls
# * 4. Should now correctly deal with spaces (%20) and other stuff in the URL
# *
# * @version 2.0
# * @author Dan Sosedoff <http://twitter.com/dan_sosedoff>
# * @author E. Akerboom <github@infostreams.net>
# */
#define('ROUTER_DEFAULT_CONTROLLER', 'home');
#define('ROUTER_DEFAULT_ACTION', 'index');
#
#class Router extends BaseClass {
#    public $request_uri;
#    public $routes;
#    public $controller, $controller_name;
#    public $action, $id;
#    public $params;
#    public $route_found = false;
#
#    def __construct():
#        $request = self.get_request();
#
#        self.request_uri = $request;
#        self.routes = array();
#    }
#
#    def get_request():
#        // find out the absolute path to this script
#        $here = str_replace("\\", "/", realpath(rtrim(dirname(__FILE__), '/')) . "/");
#
#        // find out the absolute path to the document root
#        $document_root = str_replace("\\", "/", realpath($_SERVER["DOCUMENT_ROOT"]) . "/");
#
#        // let's see if we can return a path that is expressed *relative* to the script
#        // (i.e. if this script is in '/sites/something/router.php', and we are
#        // requesting /sites/something/here/is/my/path.png, then this function will
#        // return 'here/is/my/path.png')
#        if (strpos($here, $document_root) !== false) {
#            $relative_path = "/" . str_replace($document_root, "", $here);
#
#            # fix for https://github.com/infostreams/mbtiles-php/issues/4
#            $path = $_SERVER["REQUEST_URI"];
#            if ($relative_path === '/') {
#                $path = preg_replace('/^\/+/', '', $path);
#            } else {
#                $path = urldecode(str_replace($relative_path, "", $_SERVER["REQUEST_URI"]));
#            }
#
#            return $path;
#        }
#
#        // nope - we couldn't get the relative path... too bad! Return the absolute path
#        // instead.
#        return urldecode($_SERVER["REQUEST_URI"]);
#    }
#
#    def map($rule, $target = array(), $conditions = array()):
#        self.routes[$rule] = new Route($rule, self.request_uri, $target, $conditions);
#    }
#
#    def default_routes():
#        self.map(':controller');
#        self.map(':controller/:action');
#        self.map(':controller/:action/:id');
#    }
#
#    def set_route($route):
#        self.route_found = true;
#        $params = $route->params;
#        self.controller = $params['controller']; unset($params['controller']);
#        self.action = $params['action']; unset($params['action']);
#        if (isset($params['id'])) {
#            self.id = $params['id'];
#        }
#        self.params = array_merge($params, $_GET);
#
#        if (empty(self.controller)) {
#            self.controller = ROUTER_DEFAULT_CONTROLLER;
#        }
#        if (empty(self.action)) {
#            self.action = ROUTER_DEFAULT_ACTION;
#        }
#        if (empty(self.id)) {
#            self.id = null;
#        }
#
#        // determine controller name
#        self.controller_name = implode(array_map('ucfirst', explode('_', self.controller . "_controller")));
#    }
#
#    def match_routes():
#        foreach (self.routes as $route) {
#            if ($route->is_matched) {
#                self.set_route($route);
#                break;
#            }
#        }
#    }
#
#    def run():
#        self.match_routes();
#
#        if (self.route_found) {
#            // we found a route!
#            if (class_exists(self.controller_name)) {
#                // ... the controller exists
#                $controller = new self.controller_name();
#                if (method_exists($controller, self.action)) {
#                    // ... and the action as well! Now, we have to figure out
#                    //     how we need to call this method:
#
#                    // iterate this method's parameters and compare them with the parameter names
#                    // we defined in the route. Then, reassemble the values from the URL and put
#                    // them in the same order as method's argument list.
#                    $m = new ReflectionMethod($controller, self.action);
#                    $params = $m->getParameters();
#                    $args = array();
#                    foreach ($params as $i=>$p) {
#                        if (isset(self.params[$p->name])) {
#                            $args[$i] = urldecode(self.params[$p->name]);
#                        } else {
#                            // we couldn't find this parameter in the URL! Set it to 'null' to indicate this.
#                            $args[$i] = null;
#                        }
#                    }
#
#                    // Finally, we call the function with the resulting list of arguments
#                    call_user_func_array(array($controller, self.action), $args);
#                } else {
#                    self.error(404, "Action " . self.controller_name . "." . self.action . "() not found");
#                }
#            } else {
#                self.error(404, "Controller " . self.controller_name . " not found");
#            }
#        } else {
#            self.error(404, "Page not found");
#        }
#    }
#
#}
#
#class Route {
#    public $is_matched = false;
#    public $params;
#    public $url;
#    private $conditions;
#
#    def __construct($url, $request_uri, $target, $conditions):
#        self.url = $url;
#        self.params = array();
#        self.conditions = $conditions;
#        $p_names = array();
#        $p_values = array();
#
#        // extract pattern names (catches :controller, :action, :id, etc)
#        preg_match_all('@:([\w]+)@', $url, $p_names, PREG_PATTERN_ORDER);
#        $p_names = $p_names[0];
#
#        // make a version of the request with and without the '?x=y&z=a&...' part
#        $pos = strpos($request_uri, '?');
#        if ($pos) {
#            $request_uri_without = substr($request_uri, 0, $pos);
#        } else {
#            $request_uri_without = $request_uri;
#        }
#
#        foreach (array($request_uri, $request_uri_without) as $request) {
#            $url_regex = preg_replace_callback('@:[\w]+@', array($this, 'regex_url'), $url);
#            $url_regex .= '/?';
#
#            if (preg_match('@^' . $url_regex . '$@', $request, $p_values)) {
#                array_shift($p_values);
#                foreach ($p_names as $index=>$value) {
#                    self.params[substr($value, 1)] = urldecode($p_values[$index]);
#                }
#                foreach ($target as $key=>$value) {
#                    self.params[$key] = $value;
#                }
#                self.is_matched = true;
#                break;
#            }
#        }
#
#        unset($p_names);
#        unset($p_values);
#    }
#
#    def regex_url($matches):
#        $key = str_replace(':', '', $matches[0]);
#        if (array_key_exists($key, self.conditions)) {
#            return '(' . self.conditions[$key] . ')';
#        } else {
#            return '([a-zA-Z0-9_\+\-%]+)';
#        }
#    }
#}
#?>
