import os
import re
import json
import math
import utils
import logging
import requests
import warnings
from time import mktime
from copy import deepcopy
from cache import NoCache
from decorators import retry
from datetime import datetime
from datetime import date
from .adapters import TribAdapter
from .filters import get_custom_param_value
from wsgiref.handlers import format_date_time
from .errors import (
    P2PException,
    P2PFileError,
    P2PSlugTaken,
    P2PNotFound,
    P2PForbidden,
    P2PSearchError,
    P2PTimeoutError,
    P2PRetryableError,
    P2PFileURLNotFound,
    P2PInvalidFileType,
    P2PEncodingMismatch,
    P2PUnknownAttribute,
    P2PPhotoUploadError,
    P2PInvalidAccessDefinition,
    P2PUniqueConstraintViolated
)
log = logging.getLogger('p2p')


def get_connection():
    """
    Get a connected p2p object. This function is meant to auto-discover
    the settings from your shell environment or from Django.

    We'll read these from your shell variables::

        export P2P_API_KEY=your_p2p_api_key
        export P2P_API_URL=url_of_p2p_endpoint

        # Optional
        export P2P_API_DEBUG=plz  # display an http log
        export P2P_IMAGE_SERVICES_URL=url_of_image_services_endpoint

    Or those same settings from your Django settings::

        P2P_API_KEY = your_p2p_api_key
        P2P_API_URL = url_of_p2p_endpoint
        P2P_API_DEBUG = plz  # display an http log

        # Optional
        P2P_IMAGE_SERVICES_URL = url_of_image_services_endpoint

    If you need to pass in your config, just create a new p2p object.
    """

    # Try getting settings from Django
    try:
        from django.conf import settings
        return P2P(
            url=settings.P2P_API_URL,
            auth_token=settings.P2P_API_KEY,
            debug=settings.DEBUG,
            preserve_embedded_tags=getattr(
                settings,
                'P2P_PRESERVE_EMBEDDED_TAGS',
                True
            ),
            image_services_url=getattr(
                settings,
                'P2P_IMAGE_SERVICES_URL',
                None
            )
        )
    except ImportError:
        # Try getting settings from environment variables
        if 'P2P_API_KEY' in os.environ:
            kwargs = dict(
                auth_token=os.environ['P2P_API_KEY'],
                debug=os.environ.get('P2P_API_DEBUG', False),
                preserve_embedded_tags=os.environ.get(
                    'P2P_PRESERVE_EMBEDDED_TAGS',
                    True
                ),
                image_services_url=os.environ.get(
                    'P2P_IMAGE_SERVICES_URL',
                    None
                )
            )
            if os.environ.get('P2P_API_URL', None):
                kwargs['url'] = os.environ['P2P_API_URL']
            return P2P(**kwargs)
    raise P2PException(
        "No connection settings available. Please put settings "
        "in your environment variables or your Django config"
    )


class P2P(object):
    """
    Get a connection to the P2P Content Services API::

        p2p = P2P(my_p2p_url, my_auth_token)

    You can send debug messages to stderr by using the keyword::

        p2p = P2P(my_p2p_url, my_auth_token, debug=True)

    A P2P object can cache the API calls you make. Pass a new Cache_
    object with the cache keyword::

        p2p = P2P(my_p2p_url, my_auth_token, debug=True
                  cache=DictionaryCache())

    A DictionaryCache just caches in a python variable. If you're using
    Django caching::

        p2p = P2P(my_p2p_url, my_auth_token, debug=True
                  cache=DjangoCache())
    """

    def __init__(
        self,
        auth_token,
        url="http://content-api.p2p.tribuneinteractive.com",
        debug=False,
        cache=NoCache(),
        image_services_url=None,
        product_affiliate_code='lanews',
        source_code='latimes',
        webapp_name='tRibbit',
        state_filter='working,live,pending,copyready',
        preserve_embedded_tags=True
    ):
        self.config = {
            'P2P_API_ROOT': url,
            'P2P_API_KEY': auth_token,
            'IMAGE_SERVICES_URL': image_services_url,
        }
        self.cache = cache
        self.debug = debug
        self.product_affiliate_code = product_affiliate_code
        self.source_code = source_code
        self.webapp_name = webapp_name
        self.state_filter = state_filter
        self.preserve_embedded_tags = preserve_embedded_tags

        self.default_filter = {
            'product_affiliate': self.product_affiliate_code,
            'state': self.state_filter
        }

        self.default_content_item_query = {
            'include': [
                'web_url',
                'section',
                'related_items',
                'content_topics',
                'embedded_items'
            ],
            'filter': self.default_filter
        }

        self.content_item_defaults = {
            "content_item_type_code": "blurb",
            "product_affiliate_code": self.product_affiliate_code,
            "source_code": self.source_code,
            "content_item_state_code": "live",
        }

        self.collection_defaults = {
            "productaffiliate_code": self.product_affiliate_code,
        }

        self.s = requests.Session()
        self.s.mount('https://', TribAdapter())

    def get_content_item(self, slug, query=None, force_update=False):
        """
        Get a single content item by slug.

        Takes an optional `query` parameter which is dictionary containing
        parameters to pass along in the API call. See the P2P API docs
        for details on parameters.

        Use the parameter `force_update=True` to update the cache for this
        item and query.
        """
        if not query:
            query = self.default_content_item_query

        ci = self.cache.get_content_item(slug=slug, query=query)
        if ci is None:
            j = self.get("/content_items/%s.json" % (slug), query)
            ci = j['content_item']
            self.cache.save_content_item(ci, query=query)
        elif force_update:
            j = self.get("/content_items/%s.json" % (slug),
                         query, if_modified_since=ci['last_modified_time'])
            if j:
                ci = j['content_item']
                self.cache.save_content_item(ci, query=query)
        return ci

    def get_multi_content_items(self, ids, query=None, force_update=False):
        """
        Get a bunch of content items at once. We need to use the content items
        ids to use this API call.

        The API only allows 25 items to be requested at once, so this function
        breaks the list of ids into groups of 25 and makes multiple API calls.

        Takes an optional `query` parameter which is dictionary containing
        parameters to pass along in the API call. See the P2P API docs
        for details on parameters.
        """
        ret = list()
        ids_query = list()
        if_modified_since = format_date_time(
            mktime(datetime(2000, 1, 1).utctimetuple()))

        if not query:
            query = self.default_content_item_query

        # Pull as many items out of cache as possible
        ret = [
            self.cache.get_content_item(
                id=i, query=query) for i in ids
        ]
        assert len(ids) == len(ret)

        # Go through what we had in cache and see if we need to
        # retrieve anything
        for i in range(len(ret)):
            if ret[i] is None:
                ids_query.append({
                    "id": ids[i],
                    "if_modified_since": if_modified_since,
                })
            elif force_update:
                ids_query.append({
                    "id": ids[i],
                    "if_modified_since": format_date_time(
                        mktime(ret[i]['last_modified_time'].utctimetuple())),
                })

        if len(ids_query) > 0:
            # We can only request 25 things at a time
            # so we're gonna break up the list into batches
            max_items = 25

            # we have to use <gasp>MATH</gasp>
            num_items = len(ids_query)

            # how many batches of max_items do we have?
            num_batches = int(
                math.ceil(float(num_items) / float(max_items)))

            # make a list of indices where we should break the item list
            index_breaks = [j * max_items for j in range(num_batches)]

            # break up the items into batches of 25
            batches = [ids_query[i:i + max_items] for i in index_breaks]

            resp = list()
            for items in batches:
                multi_query = query.copy()
                multi_query['content_items'] = items

                resp += self.post_json(
                    '/content_items/multi.json', multi_query)

            new_items = list()
            remove_ids = list()
            for i in range(len(ret)):
                if ret[i] is None or force_update:
                    new_item = resp.pop(0)
                    assert ids[i] == new_item['id']
                    if new_item['status'] == 200:
                        ret[i] = new_item['body']['content_item']
                        new_items.append(new_item['body']['content_item'])
                    elif new_item['status'] == 404:
                        ret[i] = None
                        remove_ids.append(ids[i])
                    elif new_item['status'] == 304:
                        continue
                    else:
                        raise P2PException(
                            '%(status)s fetching %(id)s' % new_item)

            if len(new_items) > 0:
                for i in new_items:
                    self.cache.save_content_item(i, query=query)

            try:
                if len(remove_ids) > 0:
                    for i in remove_ids:
                        self.cache.remove_content_item(id=i)
            except NotImplementedError:
                pass

        return ret

    def update_content_item(self, payload, slug=None):
        """
        Update a content item.

        Takes a single dictionary representing the content_item to be updated.
        Refer to the P2P API docs for the content item field names.

        By default this function uses the value of the 'slug' key from the
        dictionary to perform the API call. It takes an optional `slug`
        parameter in case the dictionary does not contain a 'slug' key or if
        the dictionary contains a changed slug.
        """
        content = payload.copy()

        # Check if content_item is nested or if this is a flat data structure
        if 'content_item' in content:
            content = content['content_item'].copy()
            data = payload.copy()
        else:
            data = {'content_item': content }

        # if a slug was given, remove it from the content item
        if slug is None:
            slug = content.pop('slug')

        try:
            content.pop("web_url")
        except KeyError:
            pass

        # Now that we've manipulated the content item, update
        # the payload as well
        data['content_item'] = content

        url = "/content_items/%s.json"
        url = url % slug
        if not self.preserve_embedded_tags:
            url += "?preserve_embedded_tags=false"

        resp = self.put_json(url, data)

        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass

        return resp

    def hide_right_rail(self, slug):
        """
        Hide the right rail from an HTML story. Provide the slug
        of the content item you'd like to update.
        """
        params = {
            'custom_param_data': {'htmlstory-rhs-column-ad-enable': 'false'},
        }
        return self.update_content_item(params, slug=slug)

    def show_right_rail(self, slug):
        """
        Show the right rail on an HTML story
        """
        params = {
            'custom_param_data': {'htmlstory-rhs-column-ad-enable': 'true'},
        }
        return self.update_content_item(params, slug=slug)

    def show_to_robots(self, slug):
        """
        Add metadata to the item so it is seen by robots and remove any
        noindex and nofollow tags.
        """
        params = {
            'custom_param_data': {'metadata-robots': ''},
        }
        return self.update_content_item(params, slug=slug)

    def hide_to_robots(self, slug):
        """
        Add metadata to the item so it is hidden from robots using
        the noindex and nofollow tags.
        """
        params = {
            'custom_param_data': {'metadata-robots': 'noindex, nofollow'},
        }
        return self.update_content_item(params, slug=slug)

    def search_topics(self, name):
        """
        Searches P2P for topics starting with the given name
        """
        params = {
            'name': name,
            'name_contains': True,
        }
        return self.get("/topics.json", params)

    def add_topic(self, topic_id, slug=None):
        """
        Update a topic_id item.

        Takes a single dictionary representing the topic_id_item to be updated.
        Refer to the P2P API docs for the topic_id item field names.

        By default this function uses the value of the 'slug' key from the
        dictionary to perform the API call. It takes an optional `slug`
        parameter in case the dictionary does not contain a 'slug' key or if
        the dictionary contains a changed slug.
        """

        if slug is None:
            slug = topic_id.pop('slug')

        d = {'add_topic_ids': topic_id}

        self.put_json("/content_items/%s.json" % slug, d)
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass

    def remove_topic(self, topic_id, slug=None):
        """
        Update a topic_id item.

        Takes a single dictionary representing the topic_id_item to be updated.
        Refer to the P2P API docs for the topic_id item field names.

        By default this function uses the value of the 'slug' key from the
        dictionary to perform the API call. It takes an optional `slug`
        parameter in case the dictionary does not contain a 'slug' key or if
        the dictionary contains a changed slug.
        """

        if slug is None:
            slug = topic_id.pop('slug')

        d = {'remove_topic_ids': topic_id}

        self.put_json("/content_items/%s.json" % slug, d)
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass

    def create_content_item(self, payload):
        """
        Create a new content item.

        Takes a single dictionary representing the new content item.
        Refer to the P2P API docs for the content item field names.
        """
        defaults = self.content_item_defaults.copy()
        content = payload.copy()

        # Check if content_item is nested or if this is a flat data structure
        if 'content_item' in content:
            item = content['content_item'].copy()
            defaults.update(item)
            content['content_item'] = defaults
            data = content
        else:
            content = payload.copy()
            defaults.update(content)
            data = {'content_item': defaults}

        url = '/content_items.json'
        if not self.preserve_embedded_tags:
            url += "?preserve_embedded_tags=false"

        resp = self.post_json(url, data)

        return resp

    def clone_content_item(self, slug, clone_slug, keep_embeds=False, keep_relateds=False):
        """
        Clone a P2P content item into the current market

        Takes a single dict representing the content item to be cloned.
        Refer to the P2P API docs for the content item field name

        Flags keep_embeds and keep_relateds determines whether the embedded
        and/or related items will persist in the cloned object
        """
        # Extra include vars
        query = {
            "include": [
                "contributors",
                "related_items",
                "embedded_items",
                "programmed_custom_params",
                "web_url",
                "geocodes"
            ],
        }

        # Get the full fancy content item
        content_item = self.get_content_item(slug, query)

        # Datetime string format
        fmt = '%Y-%m-%d %I:%M %p %Z'

        # Format display and publish time
        display_time_string = ''
        publish_time_string = ''
        if content_item.get('display_time'):
            display_time_string = content_item.get('display_time').strftime(fmt)

        # Format the corrections timestamp
        corrections_date = get_custom_param_value(content_item, 'corrections_date', default_value='')
        if not isinstance(corrections_date, basestring):
            corrections_date = corrections_date.strftime(fmt)

        # The story payload
        payload = {
            'slug': clone_slug,
            'title': content_item.get('title'),
            'titleline': content_item.get('titleline'),
            'kicker_id': content_item.get('kicker_id'),
            'seotitle': content_item.get('seotitle'),
            'byline': '',
            'body': content_item.get('body'),
            'dateline': content_item.get('dateline'),
            'seodescription': content_item.get('seodescription'),
            'seo_keyphrase': content_item.get('seo_keyphrase'),
            'content_item_state_code': 'working',
            'content_item_type_code': content_item.get('content_item_type_code'),
            'display_time': display_time_string,
            'product_affiliate_code': self.product_affiliate_code,
            'source_code':  content_item.get('source_code'),
            'canonical_url': content_item.get("web_url"),
        }

        # Update the custom param data
        payload['custom_param_data'] = {
            'enable-content-commenting': get_custom_param_value(content_item, 'enable-content-commenting'),
            'leadart-size': get_custom_param_value(content_item, 'lead_image_size'),
            'story-summary': get_custom_param_value(content_item, 'seodescription', default_value=''),
            'article-correction-text': get_custom_param_value(content_item, 'corrections_text', default_value=''),
            'article-correction-timestamp': corrections_date,
            'snap-user-ids': get_custom_param_value(content_item, 'snap_user_ids', default_value='')
        }

        # HTML Story specific custom params
        if payload['content_item_type_code'] == 'htmlstory':
            html_params = {
                'htmlstory-rhs-column-ad-enable': get_custom_param_value(content_item, 'htmlstory-rhs-column-ad-enable'),
                'htmlstory-headline-enable': get_custom_param_value(content_item, 'htmlstory-headline-enable'),
                'htmlstory-byline-enable': get_custom_param_value(content_item, 'htmlstory-byline-enable'),
                'disable-publication-date': get_custom_param_value(content_item, 'disable-publication-date')
            }
            payload['custom_param_data'].update(html_params)

        # Get alt_thumbnail_url and old_slug for thumbnail logic below
        alt_thumbnail_url = content_item.get('alt_thumbnail_url')

        # Only try to update if alt_thumbnail_url is a thing
        if content_item.get('alt_thumbnail_url', None):
            # data must be nested in this odd photo_upload key
            # if source code is available then it will be placed on the payload, else it will
            # default to the current users product affiliate source code
            payload['photo_upload'] = {
                'alt_thumbnail': {
                    'url': content_item.get('alt_thumbnail_url'),
                    "source_code": content_item.get('alt_thumb_source_id', self.source_code)
                }
            }

        if keep_embeds:
            # Compile the embedded items
            payload['embedded_items'] = []
            for item in content_item.get('embedded_items'):
                embed_item = {
                    'embeddedcontentitem_id': item['embeddedcontentitem_id'],
                    'headline': item['headline'],
                    'subheadline': item['subheadline'],
                    'brief': item['brief'],
                }
                payload['embedded_items'].append(embed_item)

        if keep_relateds:
            # Compile the related items
            payload['related_items'] = []
            for item in content_item.get('related_items'):
                related_item = {
                    'relatedcontentitem_id': item['relatedcontentitem_id'],
                    'headline': item['headline'],
                    'subheadline': item['subheadline'],
                    'brief': item['brief'],
                }
                payload['related_items'].append(related_item)

        contributors = self._get_cloned_contributors(content_item)

        if contributors:
            del payload['byline']
            payload['contributors'] = contributors

        # Clone the thing
        clone = self.create_content_item(payload)
        clone = clone.get('story', clone.get('html_story'))

        # if we have successfully cloned the content item, continue on
        if not clone.get('id'):
            raise P2PNotFound

        return clone['id']

    def _get_cloned_contributors(self, content_item):
        """
        Take a content item and remove the contributers

        This function is supposed to look at the byline in a content item and
        caclulate the contributers or free_form_contributers from them
        """
        clone_contributors = []

        # Split apart the byline string and iterate through it
        if content_item.get('byline', None):
            bylines = content_item.get('byline').split(',')
            for byline in bylines:

                # Preemptively create a freeform contributor
                byline = byline.strip()
                byline_item = {"free_form_name": byline}

                # Search the contributors array for a matching adv byline
                for contributor in content_item.get('contributors'):
                    # Wade through the nestedness
                    contributor = contributor['contributor']
                    if byline.lower() in contributor['title'].lower():
                        # If a match was found, update the entry with the staff slug
                        byline_item = {'slug': contributor['slug']}

                # Add the final result to the clone_contributors array
                clone_contributors.append(byline_item);
        return clone_contributors


    def delete_content_item(self, slug):
        """
        Delete the content item out of p2p
        """
        result = self.delete(
            '/content_items/%s.json' % slug)
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return True if "destroyed successfully" in result else False

    def create_or_update_content_item(self, content_item):
        """
        Attempts to update a content item, if it doesn't exist, attempts to
        create it::

            create, response = p2p.create_or_update_content_item(item_dict)

        TODO: swap the tuple that is returned.
        """
        create = False
        try:
            response = self.update_content_item(content_item)
        except P2PException:
            response = self.create_content_item(content_item)
            create = True

        return (create, response)

    def junk_content_item(self, slug):
        """
        Sets a content item to junk status.
        """
        return self.update_content_item({
            'slug': slug,
            'content_item_state_code': 'junk'
        })

    def content_item_exists(self, slug):
        """
        Checks for the existance of a slug in content services
        """
        exists = True
        try:
            self.get("/content_items/%s/exists" % (slug))
        except P2PNotFound:
            exists = False
        return exists

    def get_kickers(self, params):
        """
        Retrieves all kickers for an affiliate.
        """
        return self.get("/kickers.json", params)


    def search(self, params):
        """
        Searches P2P content items based on whatever is in the mystery params dictionary.
        """
        return self.get("/content_items/search.json", params)

    def search_collections(self, search_token, limit=20, product_affiliate_code=None):
        """
        Requests a list of collections from P2P based on search term and owner.
        """
        # Make a copy of our collection defaults
        params = deepcopy(self.collection_defaults)
        # Stick this search in there
        params['search_token'] = search_token
        # Also add the results length cutoff
        params['limit'] = limit
        # And if the user has provided a product affiliate code, override that
        if product_affiliate_code:
            params['productaffiliate_code'] = product_affiliate_code
        # Make the search and return the results
        return self.get('/collections/search.json', params)['search_results']['collections']

    def get_collection(self, code, query=None, force_update=False):
        """
        Get the data for this collection. To get the items in a collection,
        use get_collection_layout.
        """
        if query is None:
            query = {'filter': self.default_filter}

        if force_update:
            data = self.get('/collections/%s.json' % code, query)
            collection = data['collection']
            self.cache.save_collection(collection, query=query)
        else:
            collection = self.cache.get_collection(code, query=query)
            if collection is None:
                data = self.get('/collections/%s.json' % code, query)
                collection = data['collection']
                self.cache.save_collection(collection, query=query)

        return collection

    def create_collection(self, data):
        """
        Create a new collection. Takes a single argument which should be a
        dictionary of collection data.

        Example:
          p2p.create_collection({
            'code': 'my_new_collection',
            'name': 'My new collection',
            'section_path': '/news/local',
            // OPTIONAL PARAMS
            'collection_type_code': 'misc',  # default 'misc'
            'last_modified_time': date,  # defaults to now
            'product_affiliate_code': 'chinews'  # default to instance setting
          })
        """
        ret = self.post_json(
            '/collections.json?id=%s' % data['code'],
            {
                'collection': {
                    'code': data['code'],
                    'name': data['name'],
                    'collectiontype_id': data.get('collection_type_id', 1),
                    'last_modified_time': data.get('last_modified_time',
                                                   datetime.utcnow()),
                    'sequence': 999
                },
                'product_affiliate_code': data.get(
                    'product_affiliate_code', self.product_affiliate_code),
                'section_path': data['section_path']
            })

        if 'collection' in ret:
            return ret['collection']
        else:
            raise P2PException(ret)

    def delete_collection(self, code):
        """
        Delete a collection
        """
        ret = self.delete(
            '/collections/%s.json' % code)
        try:
            self.cache.remove_collection(code)
            self.cache.remove_collection_layout(code)
        except NotImplementedError:
            pass
        return ret

    def override_layout(self, code, content_item_slugs):
        """
        Override Collection Layout
        """
        ret = self.put_json(
            '/collections/override_layout.json?id=%s' % code,
            {
                'items': content_item_slugs,
                'replace_layout': 'true'
            }
        )
        try:
            self.cache.remove_collection(code)
            self.cache.remove_collection_layout(code)
        except NotImplementedError:
            pass
        return ret

    def push_into_collection(self, code, content_item_slugs):
        """
        Push a list of content item slugs onto the top of a collection
        """
        # Enforce that a list of slugs is passed in (not a string)
        if not isinstance(content_item_slugs, list):
            log.warning("[P2P][push_into_collection] content_item_slugs is not a list: %s" % content_item_slugs)
            content_item_slugs = [content_item_slugs]

        ret = self.put_json(
            '/collections/prepend.json?id=%s' % code,
            {'items': content_item_slugs})
        try:
            self.cache.remove_collection(code)
            self.cache.remove_collection_layout(code)
        except NotImplementedError:
            pass
        return ret

    def suppress_in_collection(
        self,
        code,
        content_item_slugs,
        affiliates=[]
    ):
        """
        Suppress a list of slugs in the specified collection
        """
        if not affiliates:
            affiliates.append(self.product_affiliate_code)
        ret = self.put_json(
            '/collections/suppress.json?id=%s' % code,
            {'items': [{
                'slug': slug, 'affiliates': affiliates
            } for slug in content_item_slugs]})
        try:
            self.cache.remove_collection(code)
            self.cache.remove_collection_layout(code)
        except NotImplementedError:
            pass
        return ret

    def remove_from_collection(self, code, content_item_slugs):
        """
        Push a list of content item slugs onto the top of a collection
        """
        # Enforce that a list of slugs is passed in (not a string)
        if not isinstance(content_item_slugs, list):
            log.warning("[P2P][remove_from_collection] content_item_slugs is not a list: %s" % content_item_slugs)
            content_item_slugs = [content_item_slugs]

        ret = self.put_json(
            '/collections/remove_items.json?id=%s' % code,
            {'items': content_item_slugs})
        try:
            self.cache.remove_collection(code)
            self.cache.remove_collection_layout(code)
        except NotImplementedError:
            pass
        return ret

    def insert_position_in_collection(
        self,
        code,
        slug,
        affiliates=[]
    ):
        """
        Suppress a list of slugs in the specified collection
        """
        if not affiliates:
            affiliates.append(self.product_affiliate_code)
        ret = self.put_json(
            '/collections/insert.json?id=%s' % code,
            {'items': [{
                'slug': slug, 'position': 1
            }]})
        try:
            self.cache.remove_collection(code)
            self.cache.remove_collection_layout(code)
        except NotImplementedError:
            pass
        return ret

    def append_contributors_to_content_item(self, slug, contributors):
        """
        Push a list of editorial staff slugs into a content item's
        contributors array for the display of advanced bylines
        {
          "items": [
            {
              "slug": "contributor_to_append_1"
            },
            {
              "slug": "contributor_to_append_2"
            }
          ]
        }
        """
        warnings.warn('append_contributors_to_content_item will be removed in version 2.1', DeprecationWarning)
        ret = self.put_json(
            '/content_items/%s/append_contributors.json' % slug,
            {'items': contributors})
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def remove_contributors_from_content_item(self, slug, contributors):
        """
        Pops a list of editorial staff slugs from a content item's
        contributors array
        Takes an array of slugs similar to append_contributors_to_content_item()
        """
        ret = self.put_json(
            '/content_items/%s/remove_contributors.json' % slug,
            {'items': contributors})
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def get_content_item_revision_list(self, slug, page):
        """
        Accepts a slug and returns a list of revision dictionaries
        Page should be a dict with the key 'page' and the desired number
        """
        ret = self.get('/content_items/%s/revisions.json?page=%d' % (slug, page))
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def get_content_item_revision_number(self, slug, number, query=None, related_items_query=None):
        """
        Accepts a slug and a revision number, returns dict with
        full content item information for that revision
        """
        if query is None:
            query = self.default_content_item_query

        if related_items_query is None:
            related_items_query = self.default_content_item_query

        content_item = self.get(
            '/content_items/%s/revisions/%d.json'
            % (slug, number), query)

        # Drop unnecessary outer layer
        content_item = content_item['content_item']

        # We have our content item, now loop through the related
        # items, build a list of content item ids, and retrieve them all
        ids = [item_stub['relatedcontentitem_id']
            for item_stub in content_item['related_items']
        ]

        related_items = self.get_multi_content_items(
            ids, related_items_query, False)

        # now that we've retrieved all the related items, embed them into
        # the original content item dictionary to make it fancy
        for item_stub in content_item['related_items']:
            item_stub['content_item'] = None
            for item in related_items:
                if (
                    item is not None and
                    item_stub['relatedcontentitem_id'] == item['id']
                ):
                    item_stub['content_item'] = item

        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return content_item

    def push_into_content_item(self, slug, content_item_slugs):
        """
        Push a list of content item slugs onto the top of the related
        items list for a content item
        """
        ret = self.put_json(
            '/content_items/prepend_related_items.json?id=%s' % slug,
            {'items': content_item_slugs})
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def push_embed_into_content_item(self, slug, content_item_slugs, size="S"):
        """
        Push a list of content item slugs into embedded items list

        Accepts a list of slugs and an optional size, which will be applied to
        all embeds.

            client.push_embed_into_content_item(['slug-1', 'slug-2', 'slug-3'])

            client.push_embed_into_content_item(
                ['slug-1', 'slug-2', 'slug-3'],
                size='L'
            )

        Also accepts a list of dictionaries that provide a slug and custom size
        for each embed.

            client.push_embed_into_content_item([
                dict(slug='slug-1', size='S'),
                dict(slug='slug-2', size='L'),
                dict(slug='slug-3', size='L'),
            ])
        """

        items = []
        for i, ci in enumerate(content_item_slugs):
            if isinstance(ci, str):
                d = dict(slug=ci, contentitem_size=size, position=i)
                items.append(d)
            elif isinstance(ci, dict):
                d = dict(
                    slug=ci['slug'],
                    contentitem_size=ci.get('size', size),
                    position=i
                )
                items.append(d)
            else:
                raise ValueError("content_item_slugs are bad data")
        ret = self.put_json(
            '/content_items/append_embedded_items.json?id=%s' % slug,
            {'items': items}
        )
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def remove_from_content_item(self, slug, content_item_slugs):
        """
        Removes related items from a content item, accepts slug of content item
        and list of one or more related item slugs
        """
        ret = self.put_json(
            '/content_items/remove_related_items.json?id=%s' % slug,
            {'items': content_item_slugs})
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def remove_embed_from_content_item(self, slug, content_item_slugs):
        """
        Removes embed items from a content item, accepts slug of content item
        and list of one or more related item slugs
        """
        ret = self.put_json(
            '/content_items/remove_embedded_items.json?id=%s' % slug,
            {'items': content_item_slugs})
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def insert_into_content_item(self, slug, content_item_slugs, position=1):
        """
        Insert a list of content item slugs into the related items list for
        a content item, starting at the specified position
        """
        ret = self.put_json(
            '/content_items/insert_related_items.json?id=%s' % slug,
            {'items': [{
                'slug': content_item_slugs[i], 'position': position + i
            } for i in range(len(content_item_slugs))]})
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def append_into_content_item(self, slug, content_item_slugs):
        """
        Convenience function to append a list of content item slugs to the end
        of the related items list for a content item
        """
        ci = self.get_content_item(slug)
        ret = self.insert_into_content_item(
            slug, content_item_slugs, position=(len(ci['related_items']) + 1))
        try:
            self.cache.remove_content_item(slug)
        except NotImplementedError:
            pass
        return ret

    def get_collection_layout(self, code, query=None, force_update=False):
        if not query:
            query = {
                'include': 'items',
                'filter': self.default_filter
            }

        if force_update:
            resp = self.get('/current_collections/%s.json' % code, query)
            collection_layout = resp['collection_layout']
            collection_layout['code'] = code  # response is missing this
            self.cache.save_collection_layout(collection_layout, query=query)
        else:
            collection_layout = self.cache.get_collection_layout(
                code, query=query)
            if collection_layout is None:
                resp = self.get('/current_collections/%s.json' % code, query)
                collection_layout = resp['collection_layout']
                collection_layout['code'] = code  # response is missing this
                self.cache.save_collection_layout(
                    collection_layout, query=query)

        return collection_layout

    def get_fancy_collection(
        self,
        code,
        with_collection=False,
        limit_items=25,
        content_item_query=None,
        collection_query=None,
        include_suppressed=False,
        force_update=False
    ):
        """
        Make a few API calls to fetch all possible data for a collection
        and its content items. Returns a collection layout with
        extra 'collection' key on the layout, and a 'content_item' key
        on each layout item.
        """
        collection_layout = self.get_collection_layout(
            code, query=collection_query, force_update=force_update)

        if with_collection:
            # Do we want more detailed data about the collection?
            collection = self.get_collection(
                code, query=collection_query, force_update=force_update)

            collection_layout['collection'] = collection

        if limit_items:
            # We're only going to fetch limit_items number of things
            # so cut out the extra items in the content_layout
            collection_layout['items'] = \
                collection_layout['items'][:limit_items]

        # Process the list of collection layout items to gather ids to fetch,
        # and to remove suppressed items, if necessary.
        content_item_ids = list()
        remove_these = list()
        for ci in collection_layout['items']:
            if not include_suppressed and float(ci['suppressed']) > 0:
                remove_these.append(ci)
            else:
                content_item_ids.append(ci['contentitem_id'])

        # If we're not including suppressed items, remove them from the data
        if not include_suppressed:
            for ci in remove_these:
                collection_layout['items'].remove(ci)

        # Retrieve all the content_items, 25 at a time
        content_items = self.get_multi_content_items(
            content_item_ids, query=content_item_query,
            force_update=force_update)

        # Loop through the collection items and add the corresponding content
        # item data.
        for ci in collection_layout['items']:
            for ci2 in content_items:
                if ci['contentitem_id'] == ci2['id']:
                    ci['content_item'] = ci2
                    break

        return collection_layout

    def get_fancy_content_item(
        self,
        slug,
        query=None,
        related_items_query=None,
        force_update=False
    ):
        if query is None:
            query = deepcopy(self.default_content_item_query)
            query['include'].append('related_items')

        if related_items_query is None:
            related_items_query = self.default_content_item_query

        content_item = self.get_content_item(
            slug, query, force_update=force_update)

        # We have our content item, now loop through the related
        # items, build a list of content item ids, and retrieve them all
        ids = [item_stub['relatedcontentitem_id']
               for item_stub in content_item['related_items']]

        related_items = self.get_multi_content_items(
            ids, related_items_query, force_update=force_update)

        # now that we've retrieved all the related items, embed them into
        # the original content item dictionary to make it fancy
        for item_stub in content_item['related_items']:
            item_stub['content_item'] = None
            for item in related_items:
                if (
                    item is not None and
                    item_stub['relatedcontentitem_id'] == item['id']
                ):
                    item_stub['content_item'] = item

        return content_item

    def get_section(self, path, query=None, force_update=False):
        if query is None:
            query = {
                'section_path': path,
                'product_affiliate_code': self.product_affiliate_code,
                'include': 'default_section_path_collections'
            }
        if force_update:
            data = self.get('/sections/show_collections.json', query)
            section = data
            self.cache.save_section(path, section, query)
        else:
            section = self.cache.get_section(path, query)
            if section is None:
                data = self.get('/sections/show_collections.json', query)
                section = data
                self.cache.save_section(path, section, query)

        return section

    def get_section_configs(self, path, query=None, force_update=False):
        if query is None:
            query = {
                'section_path': path,
                'product_affiliate_code': self.product_affiliate_code,
                'webapp_name': self.webapp_name
            }
        if force_update:
            data = self.get('/sections/show_configs.json', query)
            section = data
            self.cache.save_section_configs(path, section, query)
        else:
            section = self.cache.get_section_configs(path, query)
            if section is None:
                data = self.get('/sections/show_configs.json', query)
                section = data
                self.cache.save_section_configs(path, section, query)

        return section

    def get_fancy_section(self, path, force_update=False):
        section = self.get_section(path, force_update)
        config = self.get_section_configs(path, force_update)
        collections = list()
        for c in section['results']['default_section_path_collections']:
            collections.append({
                'collection_type_code': c['collection_type_code'],
                'name': c['name'],
                'collection': self.get_fancy_collection(c['code'])
            })
        fancy_section = config['results']['section_config']
        fancy_section['collections'] = collections
        fancy_section['path'] = path
        return fancy_section

    def get_nav(self, collection_code, domain=None):
        """
        get a simple dictionary of text and links for a navigation collection
        """
        nav = list()
        domain = domain.replace(
            'http://', '').replace('https://', '').replace('/', '')
        top_level = self.get_collection_layout(collection_code)
        for item in top_level['items']:
            fancy_item = self.get_fancy_content_item(item['slug'])
            if 'url' not in fancy_item:
                raise
            sub_nav = list()
            for sub_item in fancy_item['related_items']:
                if 'url' in sub_item['content_item']:
                    url = sub_item['content_item']['url']
                elif 'web_url' in sub_item['content_item']:
                    url = sub_item['content_item']['web_url']
                else:
                    raise

                if not url.startswith('http'):
                    url = 'http://' + domain + url

                sub_nav.append({
                    'text': sub_item['headline'] or
                    sub_item['content_item']['title'],
                    'url': url,
                    'slug': sub_item['slug']
                })
            if fancy_item['url'].startswith('http'):
                url = fancy_item['url']
                path = url[url.find('/') + 1:url.rfind('/')]
            else:
                url = 'http://' + domain + fancy_item['url']
                path = url[url.find('/', 7) + 1:url.rfind('/')]
            nav.append({
                'text': fancy_item['title'],
                'url': url,
                'slug': fancy_item['slug'],
                'nav': sub_nav,
                'path': path
            })
        return nav

    def get_source_product_affiliates(self, min_date='', max_date='', page=1):
        """
        Retrieves one or more product affiliate sources that have
        been modified within a designated date range.
        Why a date range?  Who knows.

        Dates must be of the format: YYYY-MM-DDTHH:MM:SSZ
        """

        # Default max_date to today if non given
        if not max_date:
            max_date = date.today().strftime("%Y-%m-%dT%I:%M:%S%Z")

        # Default min_date to the beginning of the epoch (1970)
        if not min_date:
            epoch = datetime.utcfromtimestamp(0)
            min_date = epoch.strftime("%Y-%m-%dT%I:%M:%S%Z")

        params = {
            'page': page,
            'minimum_date': min_date,
            'maximum_date': max_date
        }

        return self.get("/source_product_affiliates/multi.json", params)

    def get_product_affiliates(self, name='', code=''):
        """
        Retrieves one or more affiliate source codes.
        The Content Services endpoint takes either 'code' or 'name'
        as arguments but not both.
        """

        if name and name != 'all':
            # If a name is specified, use it
            params = {
                'name': str(name)
            }
        elif name and name == 'all':
            # Special case.  If name is "all" get everything
            params = {
                'name': ''
            }
        elif code:
            # If there is a code specified, use it instead of name
            params = {
                'code': str(code)
            }
        elif not name and not code:
            # If the args are empty, get the defualt product affiliate info
            params = {
                'code': self.product_affiliate_code
            }

        return self.get("/product_affiliates/multi.json", params)

    # Utilities
    def http_headers(self, content_type=None, if_modified_since=None):
        h = {'Authorization': 'Bearer %(P2P_API_KEY)s' % self.config}
        if content_type is not None:
            h['content-type'] = content_type
        if type(if_modified_since) == datetime:
            h['If-Modified-Since'] = format_date_time(
                mktime(if_modified_since.utctimetuple()))
        elif if_modified_since is not None:
            h['If-Modified-Since'] = if_modified_since
        return h

    def _check_for_errors(self, resp, req_url):
        """
        Parses the P2P response, scanning and raising for exceptions. When an
        exception is raised, its message will contain the response url, a curl
        string of the request and a dictionary of response data.
        """
        curl = utils.request_to_curl(resp.request)
        request_log = {
            'REQ_URL': req_url,
            'REQ_HEADERS': self.http_headers(),
            'RESP_URL': resp.url,
            'STATUS': resp.status_code,
            'RESP_BODY': resp.content,
            'RESP_HEADERS': resp.headers,
            # The time taken between sending the first byte of
            # the request and finishing parsing the response headers
            'SECONDS_ELAPSED': resp.elapsed.total_seconds()
        }

        if self.debug:
            log.debug("[P2P][RESPONSE] %s" % request_log)

        if resp.status_code >= 500:
            try:
                if u'ORA-00001: unique constraint' in resp.content:
                    raise P2PUniqueConstraintViolated(resp.url, request_log, \
curl)
                elif u'incompatible encoding regexp match' in resp.content:
                    raise P2PEncodingMismatch(resp.url, request_log, curl)
                elif u'unknown attribute' in resp.content:
                    raise P2PUnknownAttribute(resp.url, request_log, curl)
                elif u"Invalid access definition" in resp.content:
                    raise P2PInvalidAccessDefinition(resp.url, request_log, \
curl)
                elif u"solr.tila.trb" in resp.content:
                    raise P2PSearchError(resp.url, request_log, curl)
                elif u"Request Timeout" in resp.content:
                    raise P2PTimeoutError(resp.url, request_log, curl)
                elif u'Duplicate entry' in resp.content:
                    raise P2PUniqueConstraintViolated(resp.url, request_log, \
curl)
                elif (u'Failed to upload image to the photo service'
                        in resp.content):
                    raise P2PPhotoUploadError(resp.url, request_log, curl)
                elif u"This file type is not supported" in resp.content:
                    raise P2PInvalidFileType(resp.url, request_log, curl)
                elif re.search(r"The URL (.*) does not exist", resp.content):
                    raise P2PFileURLNotFound(resp.url, request_log)

                data = resp.json()

            except ValueError:
                pass
            raise P2PException(resp.url, request_log, curl)
        elif resp.status_code == 404:
            raise P2PNotFound(resp.url, request_log, curl)
        elif resp.status_code >= 400:
            if u'{"slug":["has already been taken"]}' in resp.content:
                raise P2PSlugTaken(resp.url, request_log, curl)
            elif u'{"code":["has already been taken"]}' in resp.content:
                raise P2PSlugTaken(resp.url, request_log, curl)
            elif resp.status_code == 403:
                raise P2PForbidden(resp.url, request_log, curl)
            try:
                resp.json()
            except ValueError:
                pass
            raise P2PException(resp.content, request_log, curl)
        return request_log

    @retry(P2PRetryableError)
    def get(self, url, query=None, if_modified_since=None):
        if query is not None:
            url += '?' + utils.dict_to_qs(query)

        resp = self.s.get(
            self.config['P2P_API_ROOT'] + url,
            headers=self.http_headers(if_modified_since=if_modified_since),
            verify=True
        )

        # Log the request curl if debug is on
        if self.debug:
            log.debug("[P2P][GET] %s" % utils.request_to_curl(resp.request))
        # If debug is off, store a light weight log
        else:
            log.debug("[P2P][GET] %s" % url)

        resp_log = self._check_for_errors(resp, url)

        # The API returns "Content item exists" when the /exists endpoint is called
        # causing everything to go bonkers, Why do you do this!!!
        if resp.content == "Content item exists":
            return resp.content

        try:
            ret = utils.parse_response(resp.json())
            if 'ETag' in resp.headers:
                ret['etag'] = resp.headers['ETag']
            if 'X-Total-Hits' in resp.headers:
                ret['total-hits'] = resp.headers['X-Total-Hits']
            return ret
        except ValueError:
            log.error('[P2P][GET] JSON VALUE ERROR ON SUCCESSFUL RESPONSE %s' % resp_log)
            raise

    @retry(P2PRetryableError)
    def delete(self, url):
        resp = self.s.delete(
            self.config['P2P_API_ROOT'] + url,
            headers=self.http_headers(),
            verify=True)

        # Log the request curl if debug is on
        if self.debug:
            log.debug("[P2P][DELETE] %s" % utils.request_to_curl(resp.request))
        # If debug is off, store a light weight log
        else:
            log.debug("[P2P][DELETE] %s" % url)

        self._check_for_errors(resp, url)
        return utils.parse_response(resp.content)

    @retry(P2PRetryableError)
    def post_json(self, url, data):
        payload = json.dumps(utils.parse_request(data))
        resp = self.s.post(
            self.config['P2P_API_ROOT'] + url,
            data=payload,
            headers=self.http_headers('application/json'),
            verify=True
        )

        # Log the request curl if debug is on
        if self.debug:
            log.debug("[P2P][POST] %s" % utils.request_to_curl(resp.request))
        # If debug is off, store a light weight log
        else:
            log.debug("[P2P][POST] %s" % url)

        resp_log = self._check_for_errors(resp, url)

        if resp.content == "" and resp.status_code < 400:
            return {}
        else:
            try:
                return utils.parse_response(resp.json())
            except Exception:
                log.error('[P2P][POST] EXCEPTION IN JSON PARSE: %s' % resp_log)
                raise

    @retry(P2PRetryableError)
    def put_json(self, url, data):
        payload = json.dumps(utils.parse_request(data))
        resp = self.s.put(
            self.config['P2P_API_ROOT'] + url,
            data=payload,
            headers=self.http_headers('application/json'),
            verify=True
        )

        # Log the request curl if debug is on
        if self.debug:
            log.debug("[P2P][PUT] %s" % utils.request_to_curl(resp.request))
        # If debug is off, store a light weight log
        else:
            log.debug("[P2P][PUT] %s" % url)

        resp_log = self._check_for_errors(resp, url)

        if resp.content == "" and resp.status_code < 400:
            return {}
        else:
            try:
                return utils.parse_response(resp.json())
            except Exception:
                log.error('[P2P][POST] EXCEPTION IN JSON PARSE: %s' % resp_log)
                raise
