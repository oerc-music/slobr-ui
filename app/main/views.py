from flask import render_template, request, redirect, url_for, current_app
from pprint import pprint
from datetime import datetime
from SPARQLWrapper import SPARQLWrapper, JSON
from rdflib import Graph, plugin, URIRef, Literal
from rdflib.parser import Parser
from rdflib.serializer import Serializer
import json
import re

from . import main

@main.route('/index', methods=['GET', 'POST'])
@main.route('/episodes', methods=['GET', 'POST'])
@main.route('/', methods=['GET', 'POST'])
def index():
    targets = None
    # if a source episode is provided, only list the episodes that share contributors with the source
    if request.args.get('contributorSource'):
        targets = select_same_contributor_episodes(request.args.get('contributorSource'))
    elif request.args.get('contributor'):
        targets = select_this_contributor_episodes(request.args.get('contributor').split("|"))
    episodes = select_episodes(targets)
    return render_template("index.html", episodes = episodes)

@main.route('/episode', methods=['GET', 'POST'])
def episode(): 
    if request.args.get('pid'):
        episode = select_episodes([request.args.get('pid')])[0]
        segments = select_segments_by_episode(request.args.get('pid'))
        segContrib = select_contributors_by_segments(segments)
        return render_template("episode.html", episode = episode, segContrib = segContrib)
    else:
        return redirect(url_for('.index'))


@main.route('/work', methods=['GET', 'POST'])
def work():
    if request.args.get('workid'):
        work = select_blob(request.args.get('workid'))
        contributors = select_contributors(work["dct:contributor"])
        print contributors 
        print "!!!!!"
        if "dct:isPartOf" in work:
            images = select_images_by_book(work["dct:isPartOf"])
        else:
            images = None
        print json.dumps(work, indent=4)
        return render_template("work.html", work = work, images = images, contributors = contributors)
    else:
        return redirect(url_for('.index'))

@main.route('/contributor', methods=['GET', 'POST'])
def contributor():
    if request.args.get('contributor'):
        contributor = select_blob(request.args.get('contributor'))
        external = None
        if "slobr:linkedbrainz_uri" in contributor:
            try: 
                external = select_external_contributor(contributor["slobr:linkedbrainz_uri"])
                print json.dumps(external, indent=4)
            except:
                pass
        return render_template("contributor.html", contributor=contributor, external=external)
    else: 
        return redirect(url_for('.index'))


def select_blob(uri):
    app = current_app._get_current_object()
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_blob.rq").read()
    # FIXME figure out the trusted graph cleverly
    trustedGraph = "http://slobr.linkedmusic.org/matchDecisions/DavidLewis"
    selectQuery = selectQuery.format(uri = uri,trustedGraph = trustedGraph)
    sparql.setQuery(selectQuery)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    extracted = dict()
    for r in results["results"]["bindings"]:
        if r["p"]["value"] not in extracted:
            extracted[r["p"]["value"]] = list()
        extracted[r["p"]["value"]].append(r["o"]["value"])

    context = { 
        "mo": "http://purl.org/ontology/mo/",
        "po": "http://purl.org/ontology/po/",
        "slobr": "http://slobr.linkedmusic.org/terms/",
        "dct": "http://purl.org/dc/terms/",
        "salt": "http://slobr.linkedmusic.org/salt/",
        "saltset": "http://slobr.linkedmusic.org/saltset/",
        "contrib": "http://slobr.linkedmusic.org/contributors/",
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "rdfs": "http://www.w3.org/2000/01/rdf-schema#"
    }

    g = Graph().parse(data=json.dumps(extracted), format="json-ld")
    blob = g.serialize(format="json-ld", auto_compact=True, context=context, indent=4)
    return json.loads(blob)
    
def select_episodes(episodePids=None):
    app = current_app._get_current_object()
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectEpisodesQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_episodes.rq").read()
    if episodePids is None:
        selectEpisodesQuery = selectEpisodesQuery.format(uri = "")
    else:
        epVals = "VALUES ?uri { \n"
        for ep in episodePids:
            # following weirdness is because SPARQL (or Virtuoso?) doesn't seem to like
            # VALUES parameters with expanded URIs
            epVals += "bbc:" + ep.replace(app.config["EPISODE_BASE"], "") + "\n"
        epVals += "}"
        selectEpisodesQuery = selectEpisodesQuery.format(uri = epVals)
    sparql.setQuery(selectEpisodesQuery)
    sparql.setReturnFormat(JSON)
    episodeResults = sparql.query().convert()
    episodes = list()
    for e in episodeResults["results"]["bindings"]:
        date = datetime.strftime(
                 datetime.strptime(
                   e["date"]["value"][:10], #don't care about the time
                   "%Y-%m-%d"), 
                 "%A %B %d %Y"
               )
        epResults = {
            "uri": e["uri"]["value"],
            "pid": e["uri"]["value"].replace("http://slobr.linkedmusic.org/", ""),
            "title": e["title"]["value"],
            "date": date,
            "short_synopsis": e["short_synopsis"]["value"],
            "medium_synopsis": e["medium_synopsis"]["value"],
            "long_synopsis": e["long_synopsis"]["value"],
            "image": e["image"]["value"].replace("http://slobr.linkedmusic.org/bbcimages/", "")
        }
        if "nextEpisode" in e:
            epResults["nextEpisode"] = e["nextEpisode"]["value"] 
        if "previousEpisode" in e:
            epResults["previousEpisode"] =  e["previousEpisode"]["value"]
        episodes.append(epResults)
    return episodes


def select_segments_by_episode(episodePid):
    app = current_app._get_current_object()
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectSegmentsQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_segments_by_episode.rq").read()
    selectSegmentsQuery = selectSegmentsQuery.format(uri = "BIND(<" + episodePid + "> as ?uri) .")
    sparql.setQuery(selectSegmentsQuery)
    sparql.setReturnFormat(JSON)
    segmentResults = sparql.query().convert()
    segments = list()
    for s in segmentResults["results"]["bindings"]:
        segEventPosition = s["segEventsPosition"] if "segEventPosition" in s else None
        segments.append({
            "segEvents": s["segEvents"]["value"],
            "segEventsPosition": segEventPosition,
            "segment": s["segment"]["value"]
            })
    return segments 

def select_contributors(contrib):
    app = current_app._get_current_object()
    contributor = "VALUES ?contributor { \n"
    for c in contrib:
        # following weirdness is because SPARQL (or Virtuoso?) doesn't seem to like
        # VALUES parameters with expanded URIs
        contributor += c.replace("http://slobr.linkedmusic.org/contributors/", "contr:") + "\n"
    contributor += "}"
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectContributorsQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_contributors.rq").read()
    selectContributorsQuery = selectContributorsQuery.format(contributor = contributor)
    sparql.setQuery(selectContributorsQuery)
    sparql.setReturnFormat(JSON)
    contributorResults = sparql.query().convert()
    contributors = dict()
    for cR in contributorResults["results"]["bindings"]:
        contributors[cR["contributor"]["value"]] = cR["name"]["value"]
    return contributors

def select_contributors_by_segments(segments):   
    app = current_app._get_current_object()
    segids = ""
    for s in segments:
        # following weirdness is because SPARQL (or Virtuoso?) doesn't seem to like
        # VALUES parameters with expanded URIs
        segids +=  "bbc:" + s["segment"].replace(app.config["EPISODE_BASE"], "") + "\n"
    if not segids:
        return None # some episodes don't have segments
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectContributorsQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_contributors_by_segments.rq").read()
    selectContributorsQuery = selectContributorsQuery.format(segments=segids)
    sparql.setQuery(selectContributorsQuery)
    sparql.setReturnFormat(JSON)
    contributorResults = sparql.query().convert()
    segments = dict()
    for s in contributorResults["results"]["bindings"]:
        segid = s["segment"]["value"]
        if segid not in segments:
            segments[segid] = { 
                "title": s["title"]["value"],
                "contributors" : list()
            }
        segments[segid]["contributors"].append({
            "contributorUri": s["contributor"]["value"],
            "contributorName": s["name"]["value"]
        })

    return segments


def select_same_contributor_episodes(sourceEpisode):
    app = current_app._get_current_object()
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectContributorsQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_same_contributor_episodes.rq").read()
    sourceEpisode = "BIND(<" + sourceEpisode + "> as ?sourceEpisode) ."
    selectContributorsQuery = selectContributorsQuery.format(sourceEpisode = sourceEpisode)
    print selectContributorsQuery
    sparql.setQuery(selectContributorsQuery)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    episodes = list()
    for r in results["results"]["bindings"]:
        episodes.append(r["targetEpisode"]["value"])
    return episodes 

def select_this_contributor_episodes(contributors):
    app = current_app._get_current_object()
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectEpisodesQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_this_contributor_episodes.rq").read()
    contributor = "VALUES ?contributor { \n"
    for c in contributors:
        # following weirdness is because SPARQL (or Virtuoso?) doesn't seem to like
        # VALUES parameters with expanded URIs
        contributor += c.replace("http://slobr.linkedmusic.org/contributors/", "contr:") + "\n"
    contributor += "}"
    selectEpisodesQuery = selectEpisodesQuery.format(contributor = contributor)
    sparql.setQuery(selectEpisodesQuery)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    episodes = list()
    for r in results["results"]["bindings"]:
        episodes.append(r["targetEpisode"]["value"])
    return episodes 

def select_images_by_book(books):
    app = current_app._get_current_object()
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectImagesQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_images_by_book.rq").read()
    b = "VALUES ?book { \n" 
    for book in books:
        b += "<" + book + ">\n"
    b += " }"
    selectImagesQuery = selectImagesQuery.format(book = b)
    sparql.setQuery(selectImagesQuery)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    images = list()
    for r in results["results"]["bindings"]:
        images.append(r["image"]["value"])
    return images 

def select_external_contributor(linkedbrainz):
    app = current_app._get_current_object()
    sparql = SPARQLWrapper(app.config["ENDPOINT"])
    sparql.setCredentials(user = app.config["SPARQLUSER"], passwd = app.config["SPARQLPASSWORD"])
    selectExternalQuery = open(app.config["SLOBR_QUERY_DIR"] + "select_external_contributor.rq").read()
    linkedbrainz = "BIND(<" + linkedbrainz + ">as ?linkedbrainz) ."
    selectExternalQuery = selectExternalQuery.format(linkedbrainz = linkedbrainz)
    sparql.setQuery(selectExternalQuery)
    sparql.setReturnFormat(JSON)
    results = sparql.query().convert()
    external = dict()
    for r in results["results"]["bindings"]:
        for key in r:
            external[key] = r[key]["value"]
#            external["image"] = r["image"]["value"]
#            external["birth"] = r["birth"]["value"]
#            external["death"] = r["death"]["value"]
#            external["bio"] = r["bio"]["value"]

    return external 

