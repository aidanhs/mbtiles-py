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
from bottle import abort, response

import sqlite3, os, re, glob, indent, cgi
app = bottle.Bottle()

app.router.add_filter('_identifier', lambda c: re.compile(r'[\d_-\s]+'))
app.router.add_filter('_number', lambda c: re.compile(r'\d+'))

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
    return TileMapServiceController().resource(layer)

class BaseClass(object):

    def __init__(self, *args, **kwargs):
        super(BaseClass, self).__init__(*args, **kwargs)
        self._layer = None
        self._db = None

    def getMBTilesName(self):
        return self._layer + ".mbtiles"

    def openDB(self):
        filename = self.getMBTilesName()

        if os.path.isfile(filename):
            self._db = sqlite3.connect(filename)
        else:
            abort(404, "Incorrect tileset name: " + self._layer)

    def closeDB(self):
        self._db.close()

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
            if len(route.rule) > 1 and "<layer>" not in route.url:
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

    def root():
        base = self.getBaseUrl();

        header('Content-type: text/xml');
        return indent.dedent("""\
            <?xml version="1.0" encoding="UTF-8" ?>
            <Services>
                <TileMapService title="%s" version="%s" href="%s%s/" />
            </Services>""" % (self.server_name, self.server_version, base, self.server_version))

    def service():
        base = self.getBaseUrl()

        response.set_header('Content-type', 'text/xml')
        ret = ''
        ret += "<?xml version=\"1.0\" encoding=\"UTF-8\" ?>";
        ret += "\n<TileMapService version=\"1.0.0\" services=\"%s\">" % (base,);
        ret += "\n\t<Title>{self.server_name} v{self.server_version}</Title>";
        ret += "\n\t<Abstract />";

        ret += "\n\t<TileMaps>";

        for dbfile in glob.glob('*.mbtiles'):
            if not os.path.isfile(dbfile):
                continue
            try:
                aidan
                db = sqlite3.connect(dbfile)
                params = self.readparams(db);
                name = cgi.escape(params['name']).encode('ascii', 'xmlcharrefreplace')
                identifier = dbfile.replace('.mbtiles', '')
                ret += "\n\t\t<TileMap title=\"%s\" srs=\"OSGEO:41001\" profile=\"global-mercator\" href=\"%s1.0.0/%s\" />" % (name, base, identifier);
            except DatabaseError as e:
                pass

        ret += "\n\t</TileMaps>";
        ret += "\n</TileMapService>";
        return ret

    def resource(layer):
        ret = ''
        try:
            self._layer = layer;
            self.openDB();
            params = self.readparams(self._db);

            title = htmlspecialchars(params['name']);
            description = htmlspecialchars(params['description']);
            fmt = params['format'];

            if fmt.lower in ["jpg","jpeg"]:
                mimetype = "image/jpeg";
            else:
                format = "png";
                mimetype = "image/png";

            base = self.getBaseUrl();
            response.set_header('Content-type', 'text/xml')
            ret += indent.dedent("""\
                <?xml version="1.0" encoding="UTF-8" ?>
                <TileMap version="1.0.0" tilemapservice="%s1.0.0/">
                    <Title>%s</Title>
                    <Abstract>%s</Abstract>
                    <SRS>OSGEO:41001</SRS>
                    <BoundingBox minx="-180" miny="-90" maxx="180" maxy="90" />
                    <Origin x="0" y="0"/>
                    <TileFormat width="256" height="256" mime-type="%s" extension="%s"/>
                    <TileSets profile="global-mercator">""" % (base, title, description, mimetype, fmt))

            for zoom in self.readzooms(self.db):
                href = base + "1.0.0/" + self.layer + "/" + zoom;
                units_pp = 78271.516 / pow(2, zoom);

                ret += "<TileSet href=\"%s\" units-per-pixel=\"%s\" order=\"%s\" />" % (href, units_pp, zoom);
            ret += indent.dedent("""\
                    </TileSets>
                </TileMap>""")
        except DatabaseError as e:
            abort(404, "Incorrect tileset name: " . self.layer)

    def readparams(db):
        params = {};
        cur = db.cursor()
        cur.execute('select name, value from metadata')
        result = cur.fetchall()
        for name, value in result:
            params[name] = value;
        return params;

    def readzooms(db):
        params = self.readparams(db);
        minzoom = params['minzoom'];
        maxzoom = params['maxzoom'];
        return range(minzoom, maxzoom + 1);

    def getBaseUrl():
        return "http://localhost:8080/"
        # TODO
        #$protocol = empty($_SERVER["HTTPS"])?"http":"https";
        #return $protocol . '://' . $_SERVER['HTTP_HOST'] . preg_replace('/\/(1.0.0\/)?[^\/]*$/', '/', $_SERVER['REQUEST_URI']);


app.run()


#$r->map("1.0.0/:layer/:z/:x/:y.:ext",
#        array("controller"=>"maptile", "action"=>"serveTmsTile"),
#        array("layer"=>$_identifier, "x"=>$_number, "y"=>$_number, "z"=>$_number,
#              "ext"=>"(png|jpg|jpeg|json)"));
#
#$r->map(":layer/:z/:x/:y.:ext",
#        array("controller"=>"maptile", "action"=>"serveTile"),
#        array("layer"=>$_identifier, "x"=>$_number, "y"=>$_number, "z"=>$_number,
#              "ext"=>"(png|jpg|jpeg|json)"));
#
#$r->map(":layer/:z/:x/:y.:ext\?:argument=:callback",
#        array("controller"=>"maptile", "action"=>"serveTile"),
#        array("layer"=>$_identifier, "x"=>$_number, "y"=>$_number, "z"=>$_number,
#              "ext"=>"(json|jsonp)", "argument"=>$_identifier, "callback"=>$_identifier));
#
#$r->map(":layer/:z/:x/:y.grid.:ext",
#        array("controller"=>"maptile", "action"=>"serveTile"),
#        array("layer"=>$_identifier, "x"=>$_number, "y"=>$_number, "z"=>$_number,
#              "ext"=>"(json|jsonp)", "argument"=>$_identifier, "callback"=>$_identifier));
#
#$r->map(":layer/:z/:x/:y.grid.:ext\?:argument=:callback",
#        array("controller"=>"maptile", "action"=>"serveTile"),
#        array("layer"=>$_identifier, "x"=>$_number, "y"=>$_number, "z"=>$_number,
#              "ext"=>"(json|jsonp)", "argument"=>$_identifier, "callback"=>$_identifier));
#
#$r->map(":layer.tilejson",
#        array("controller"=>"maptile", "action"=>"tilejson"), array("layer"=>$_identifier));
#
#$r->map(":layer.tilejsonp\?:argument=:callback",
#        array("controller"=>"maptile", "action"=>"tilejson"),
#        array("layer"=>$_identifier, "argument"=>$_identifier, "callback"=>$_identifier));
#
#$r->run();
#
#
#


#class MapTileController extends BaseClass {
#    protected $x;
#    protected $y;
#    protected $z;
#    protected $tileset;
#    protected $ext;
#    protected $is_tms;
#
#    def __construct():
#        self.is_tms = false;
#    }
#
#    def set($layer, $x, $y, $z, $ext, $callback):
#        self.layer = $layer;
#        self.x = $x;
#        self.y = $y;
#        self.z = $z;
#        self.ext = $ext;
#        self.callback = $callback;
#    }
#
#    def serveTile($layer, $x, $y, $z, $ext, $callback):
#        self.set($layer, $x, $y, $z, $ext, $callback);
#
#        if (!self.is_tms) {
#            self.y = pow(2, self.z) - 1 - self.y;
#        }
#
#        switch (strtolower(self.ext)) {
#            case "json" :
#            case "jsonp" :
#                if (is_null(self.callback)) {
#                    self.jsonTile();
#                } else {
#                    self.jsonpTile();
#                }
#                break;
#
#            case "png" :
#            case "jpeg" :
#            case "jpg" :
#                self.imageTile();
#                break;
#        }
#    }
#
#    def serveTmsTile($tileset, $x, $y, $z, $ext, $callback):
#        self.is_tms = true;
#
#        self.serveTile($tileset . "-tms", $x, $y, $z, $ext, $callback);
#    }
#
#    def jsonTile():
#        $etag = self.etag("json");
#        self.checkCache($etag);
#
#        $json = self.getUTFgrid();
#
#        // disable ZLIB ouput compression
#        ini_set('zlib.output_compression', 'Off');
#
#        // serve JSON file
#        header('Content-Type: application/json; charset=utf-8');
#        header('Content-Length: ' . strlen($json));
#        self.cachingHeaders($etag);
#
#        echo $json;
#    }
#
#    def jsonpTile():
#        $etag = self.etag("jsonp");
#        self.checkCache($etag);
#
#        $json = self.getUTFgrid();
#        $output = self.callback . "($json)";
#
#        // disable ZLIB output compression
#        ini_set('zlib.output_compression', 'Off');
#
#        // serve JSON file
#        header('Content-Type: application/json; charset=utf-8');
#        header('Content-Length: ' . strlen($output));
#        self.cachingHeaders($etag);
#
#        echo $output;
#    }
#
#    def etag($type):
#        return sha1(sprintf("%s-%s-%s-%s-%s-%s", self.tileset, self.x, self.y, self.z, $type, filemtime(self.getMBTilesName())));
#    }
#
#    def checkCache($etag):
#        if (isset($_SERVER['HTTP_IF_NONE_MATCH']) && $_SERVER['HTTP_IF_NONE_MATCH'] == $etag) {
#            header('HTTP/1.1 304 Not Modified');
#            exit();
#        }
#    }
#
#    def cachingHeaders($etag=null):
#        $day = 60*60*24;
#        $expires = 1 * $day;
#
#        // For an explanation on how the expires header and the etag header work together,
#        // please see http://stackoverflow.com/a/500103/426224
#        header("Expires: " . gmdate('D, d M Y H:i:s', time()+$expires));
#        header("Pragma: cache");
#        header("Cache-Control: max-age=$expires");
#        if (is_string($etag)) {
#            header("ETag: {$etag}");
#        }
#    }
#
#    def imageTile():
#        $etag = self.etag("img");
#        self.checkCache($etag);
#
#        if (self.is_tms) {
#            self.tileset = substr(self.tileset, 0, strlen(self.tileset) - 4);
#        }
#
#        try {
#            self.openDB();
#
#            $result = self.db->query('select tile_data as t from tiles where zoom_level=' . self.z . ' and tile_column=' . self.x . ' and tile_row=' . self.y);
#            $data = $result->fetchColumn();
#
#            if (!isset($data) || $data === FALSE) {
#
#                // did not find a tile - return an empty (transparent) tile
#                $png = imagecreatetruecolor(256, 256);
#                imagesavealpha($png, true);
#                $trans_colour = imagecolorallocatealpha($png, 0, 0, 0, 127);
#                imagefill($png, 0, 0, $trans_colour);
#                header('Content-type: image/png');
#                self.cachingHeaders($etag);
#                imagepng($png);
#
#            } else {
#
#                // Hooray, found a tile!
#                // - figure out which format (jpeg or png) it is in
#                $result = self.db->query('select value from metadata where name="format"');
#                $resultdata = $result->fetchColumn();
#                $format = isset($resultdata) && $resultdata !== FALSE ? $resultdata : 'png';
#                if ($format == 'jpg') {
#                    $format = 'jpeg';
#                }
#
#                // - serve the tile
#                header('Content-type: image/' . $format);
#                self.cachingHeaders($etag);
#                print $data;
#
#            }
#
#            // done
#            self.closeDB();
#        }
#        catch( PDOException $e ) {
#            self.closeDB();
#            self.error(500, 'Error querying the database: ' . $e->getMessage());
#        }
#    }
#
#    def getUTFgrid():
#        self.openDB();
#
#        try {
#            $flip = true;
#            if (self.is_tms) {
#                self.tileset = substr(self.tileset, 0, strlen(self.tileset) - 4);
#                $flip = false;
#            }
#
#            $result = self.db->query('select grid as g from grids where zoom_level=' . self.z . ' and tile_column=' . self.x . ' and tile_row=' . self.y);
#
#            $data = $result->fetchColumn();
#            if (!isset($data) || $data === FALSE) {
#                // nothing found - return empty JSON object
#                return "{}";
#            } else {
#                // get the gzipped json from the database
#                $grid = gzuncompress($data);
#
#                // manually add the data for the interactivity layer by means of string manipulation
#                // to prevent a bunch of costly calls to json_encode & json_decode
#                //
#                // first, strip off the last '}' character
#                $grid = substr(trim($grid),0,-1);
#                // then, add a new key labelled 'data'
#                $grid .= ',"data":{';
#
#                // stuff that key with the actual data
#                $result = self.db->query('select key_name as key, key_json as json from grid_data where zoom_level=' . self.z . ' and tile_column=' . self.x . ' and tile_row=' . self.y);
#                while ($row = $result->fetch(PDO::FETCH_ASSOC)) {
#                    $grid .= '"' . $row['key'] . '":' . $row['json'] . ',';
#                }
#
#                // finish up
#                $grid = rtrim($grid,',') . "}}";
#
#                // done
#                return $grid;
#            }
#        }
#        catch( PDOException $e ) {
#            self.closeDB();
#            self.error(500, 'Error querying the database: ' . $e->getMessage());
#        }
#    }
#
#    def tileJson($layer, $callback):
#        self.layer = $layer;
#        self.openDB();
#        try {
#            $tilejson = array();
#            $tilejson['tilejson'] = "2.0.0";
#            $tilejson['scheme'] = "xyz";
#
#            $result = self.db->query('select name, value from metadata');
#            while ($row = $result->fetch(PDO::FETCH_ASSOC)) {
#                $key = trim($row['name']);
#                $value = $row['value'];
#                if (in_array($key, array('maxzoom', 'minzoom'))) {
#                    $value = intval($value);
#                }
#                $tilejson[$key] = $value;
#            }
#            if (array_key_exists('bounds', $tilejson)) {
#                $tilejson['bounds'] = array_map('floatval', explode(',', $tilejson['bounds']));
#            }
#            if (array_key_exists('center', $tilejson)) {
#                $tilejson['center'] = array_map('floatval', explode(',', $tilejson['center']));
#            }
#
#            // find out the absolute URL to this script
#            $protocol = empty($_SERVER["HTTPS"])?"http":"https";
#            $server_url = $protocol . "://" . $_SERVER["HTTP_HOST"] . dirname($_SERVER["REQUEST_URI"]);
#
#            $tilejson['tiles'] = array(
#                $server_url . "/" . urlencode($layer) . "/{z}/{x}/{y}.png"
#            );
#            $tilejson['grids'] = array(
#                $server_url . "/" . urlencode($layer) . "/{z}/{x}/{y}.json"
#            );
#
#            if ($callback !== null) {
#                $json = "$callback(" . json_encode($tilejson) . ")";
#            } else {
#                $json = json_encode($tilejson);
#            }
#
#            ini_set('zlib.output_compression', 'Off');
#            header('Content-Type: application/json');
#            header('Content-Length: ' . strlen($json));
#            self.cachingHeaders();
#
#            echo $json;
#        }
#        catch( PDOException $e ) {
#            self.closeDB();
#            self.error(500, 'Error querying the database: ' . $e->getMessage());
#        }
#    }
#
#}
#

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
