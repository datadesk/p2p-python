from builtins import range
import pprint
import unittest
from p2p import (
    get_connection,
    P2PNotFound,
    P2PSlugTaken,
    filters,
    P2PFileURLNotFound,
    P2PUniqueConstraintViolated
)
pp = pprint.PrettyPrinter(indent=4)


class BaseP2PTest(unittest.TestCase):
    content_item_keys = (
        'altheadline', 'expire_time',
        'canonical_url', 'mobile_title', 'create_time',
        'source_name', 'last_modified_time', 'seodescription',
        'exclusivity', 'content_type_group_code', 'byline',
        'title', 'dateline', 'brief', 'id', 'web_url', 'body',
        'display_time', 'publish_time', 'undated', 'is_opinion',
        'columnist_id', 'live_time', 'titleline',
        'ad_exclusion_category', 'product_affiliate_code',
        'content_item_state_code', 'seo_redirect_url', 'slug',
        'content_item_type_code', 'deckheadline', 'seo_keyphrase',
        'mobile_highlights', 'subheadline', 'thumbnail_url',
        'source_code', 'ad_keywords', 'seotitle', 'alt_thumbnail_url'
    )
    collection_keys = (
        'created_at', 'code', 'name',
        'sequence', 'max_elements', 'productaffiliatesection_id',
        'last_modified_time', 'collection_type_code',
        'exclusivity', 'id'
    )
    content_layout_keys = (
        'code', 'items', 'last_modified_time', 'collection_id', 'id'
    )
    content_layout_item_keys = (
        'content_item_type_code', 'content_item_state_code',
        'sequence', 'headline', 'abstract',
        'productaffiliatesection_id', 'slug', 'subheadline',
        'last_modified_time', 'contentitem_id', 'id'
    )
    p2p = get_connection()
    test_story_slugs = ["la-test-p2p-python-temp-story-%s" % x for x in range(0, 8)]
    first_test_story_slug = "la-test-p2p-python-temp-story-0"
    test_htmlstory_slug = "la-test-p2p-python-temp-htmlstory"
    test_photo_slug = "la-test-p2p-python-temp-photo"
    test_collection_codes = ["la-test-p2p-python-collection-%s" % x for x in range(0, 3)]
    first_test_collection_code = "la-test-p2p-python-collection-0"
    second_test_collection_code = "la-test-p2p-python-collection-1"


    @classmethod
    def setUpTestStories(cls):
        # Make sure everything is cleared out first
        for slug in cls.test_story_slugs:
            try:
                cls.p2p.delete_content_item(slug)
            except P2PNotFound:
                pass

        # Create a bunch of test stories and store to self.test_story_slugs
        for slug in cls.test_story_slugs:
            cls.p2p.create_content_item({
                "slug": slug,
                "content_item_type_code": "story",
                "title": "Temporary content item #%s for unittesting" % slug,
                "body": "Placeholder body for %s" % slug
            })


    @classmethod
    def setUpTestHTMLStories(cls):
        # Make sure everything is cleared out first
        try:
            cls.p2p.delete_content_item(cls.test_htmlstory_slug)
        except P2PNotFound:
                pass

        # Create a test htmlstory
        cls.p2p.create_or_update_content_item({
            "slug": cls.test_htmlstory_slug,
            "content_item_type_code": "htmlstory",
            "title": "Temporary htmlstory for unittesting",
            "body": "Placeholder body for the htmlstory"
        })

    @classmethod
    def setUpTestPhoto(cls):
        # Make sure everything is cleared out first
        try:
            cls.p2p.delete_content_item(cls.test_photo_slug)
        except P2PNotFound:
                pass

        # Create a test htmlstory
        cls.p2p.create_or_update_content_item({
            "slug": cls.test_photo_slug,
            "content_item_type_code": "photo",
            "title": "Temporary photo for unittesting",
        })

    @classmethod
    def setUpTestCollections(cls):
        # Make sure everything is cleared out first
        for slug in cls.test_collection_codes:
            try:
                cls.p2p.delete_collection(slug)
            except P2PNotFound:
                pass

        for slug in cls.test_collection_codes:
            try:
                cls.p2p.get_collection_layout(slug)
            except P2PNotFound:
                cls.p2p.create_collection({
                    'code': slug,
                    'name': 'Test collection #%s created via API' % slug,
                    'section_path': '/test'
                })

    def setUp(self):
        self.p2p.debug = True
        self.p2p.config['IMAGE_SERVICES_URL'] = 'http://image.p2p.tribuneinteractive.com'


class StoryAndPhotoTest(BaseP2PTest):

    @classmethod
    def setUpClass(cls):
        cls.setUpTestStories()
        cls.setUpTestHTMLStories()
        cls.setUpTestPhoto()

    def test_create_or_update_content_item(self):
        # Story
        self.p2p.create_or_update_content_item({
            "slug": self.first_test_story_slug,
            "title": "Test content item",
            "content_item_state_code": "working"
        })
        # HTML story
        self.p2p.create_or_update_content_item({
            "slug": self.test_htmlstory_slug,
            "title": "Test HTML story"
        })

    def test_update_content_item_with_topics(self):
        topics = [
            "PEPLT007408",
            "OREDU0000173"
        ]

        # Add topics to the story
        self.p2p.update_content_item({
            "add_topic_ids": topics,
            "content_item": {
                "slug": self.first_test_story_slug,
            },
        })

        # Add content_topics to our content item query
        query = self.p2p.default_content_item_query
        query["include"].append("content_topics")

        # Make sure the topics were added correctly
        data = self.p2p.get_fancy_content_item(self.first_test_story_slug, query=query)
        self.assertEqual(
            len(data["content_topics"]),
            len(topics)
        )

        # Now let's remove the topics
        self.p2p.update_content_item({
            "remove_topic_ids": topics,
            "content_item": {
                "slug": self.first_test_story_slug,
            },
        })

        # Make sure the topics were removed correctly
        data = self.p2p.get_fancy_content_item(self.first_test_story_slug)
        self.assertEqual(len(data["content_topics"]), 0)

    def test_get_content_item(self):
        # Story
        data = self.p2p.get_content_item(self.first_test_story_slug)
        for k in self.content_item_keys:
            self.assertIn(k, list(data.keys()))
        # HTML story
        data = self.p2p.get_content_item(self.test_htmlstory_slug)
        for k in self.content_item_keys:
            self.assertIn(k, list(data.keys()))

    def test_related_items(self):
        # Add
        self.p2p.push_into_content_item(
            self.test_htmlstory_slug, [self.first_test_story_slug])
        data = self.p2p.get_content_item(self.test_htmlstory_slug)
        self.assertEqual(len(data["related_items"]), 1)
        # Remove
        self.p2p.remove_from_content_item(
            self.test_htmlstory_slug, [self.first_test_story_slug])
        data = self.p2p.get_content_item(self.test_htmlstory_slug)
        self.assertEqual(len(data["related_items"]), 0)

    def test_embedded_items(self):
        # Clear out any embedded items
        self.p2p.remove_embed_from_content_item(
            self.test_htmlstory_slug,
            [self.first_test_story_slug, self.test_photo_slug]
        )
        # Add embedded items
        self.p2p.push_embed_into_content_item(
            self.test_htmlstory_slug,
            [self.first_test_story_slug],
            size="S"
        )
        data = self.p2p.get_content_item(self.test_htmlstory_slug)
        self.assertEqual(len(data["embedded_items"]), 1)
        self.p2p.push_embed_into_content_item(
            self.test_htmlstory_slug,
            [dict(slug=self.test_photo_slug, size='J')]
        )
        data = self.p2p.get_content_item(self.test_htmlstory_slug)
        self.assertEqual(len(data["embedded_items"]), 2)
        # Remove
        self.p2p.remove_embed_from_content_item(
            self.test_htmlstory_slug,
            [self.first_test_story_slug, self.test_photo_slug]
        )
        data = self.p2p.get_content_item(self.test_htmlstory_slug)
        self.assertEqual(len(data["embedded_items"]), 0)

    def test_add_remove_contributors(self):
        test_contributor_1 = {"slug": "la-tester-20160727"}
        test_contributor_2 = {"slug": "la-test-testtest-20140528"}

        # Add a contributor
        self.p2p.append_contributors_to_content_item(
            self.first_test_story_slug,
            [test_contributor_1]
        )

        # Add contributors to our content item query
        query = self.p2p.default_content_item_query
        query['include'].append('contributors')

        # Check that a contributor was added
        data = self.p2p.get_content_item(self.first_test_story_slug, query)
        self.assertEqual(len(data["contributors"]), 1)

        # Add another contributor
        self.p2p.append_contributors_to_content_item(
            self.first_test_story_slug,
            [test_contributor_2]
        )

        # Check that we now have two contributors
        data = self.p2p.get_content_item(self.first_test_story_slug, query)
        self.assertEqual(len(data["contributors"]), 2)

        # Remove the contributors
        test_contributors = [
            test_contributor_1,
            test_contributor_2
        ]
        self.p2p.remove_contributors_from_content_item(
            self.first_test_story_slug,
            test_contributors
        )

        data = self.p2p.get_content_item(self.first_test_story_slug, query)
        self.assertEqual(len(data["contributors"]), 0)

    def test_create_update_delete_content_item(self):
        data = {
            'slug': 'la_na_test_create_update_delete',
            'title': 'Testing creating, updating and deletion',
            'body': 'Updated info',
            'content_item_type_code': 'story',
        }

        try:
            result = self.p2p.create_content_item(data)
        except P2PSlugTaken:
            self.p2p.delete_content_item(data['slug'])
            result = self.p2p.create_content_item(data)

        data2 = data.copy()
        data2['body'] = 'Lorem ipsum foo bar'
        result2 = self.p2p.update_content_item(data2)
        self.assertTrue(self.p2p.delete_content_item(data['slug']))

        self.assertIn(data['content_item_type_code'], result)
        res = result[data['content_item_type_code']]
        self.assertEqual(res['slug'], data['slug'])
        self.assertEqual(res['title'], data['title'])
        self.assertEqual(res['body'].strip(), data['body'])

        res = result2
        self.assertEqual(res, {})

    def test_clone_delete_content_item(self):
        # The content item to clone
        slug = self.first_test_story_slug

        # Why? Why does this give a different web url
        # than in the default query?
        query = {
            "include": [
                "web_url",
            ],
        }

        # Get the original content item to compare later
        original_item = self.p2p.get_content_item(slug, query)

        # Clone it!
        clone_id = self.p2p.clone_content_item(slug, "la-cloned-test-story-99999999")
        clone = self.p2p.get_content_item(clone_id)
        self.p2p.delete_content_item(clone_id)

        # Check that everything is ok
        self.assertNotEqual(
            clone['slug'],
            original_item['slug'],
            "Cloned content item's slug should not match the original content item's slug"
        )
        self.assertEqual(
            clone['title'],
            original_item['title'],
            "Cloned content item's title should match the original content item's title"
        )
        self.assertEqual(
            clone['canonical_url'],
            original_item['web_url'],
            "Cloned content item's canonical url should match the original content item's web url"
        )

    def test_content_item_exists(self):
        slug = 'la_na_test_content_item_exists'
        data = {
            'slug': slug,
            'title': 'Testing content item exists',
            'body': 'Updated info',
            'content_item_type_code': 'story',
        }

        # Create the content item, delete if exists and recreate.
        try:
            self.p2p.create_content_item(data)
        except P2PSlugTaken:
            self.p2p.delete_content_item(slug)
            self.p2p.create_content_item(data)

        # make sure it's there
        self.assertTrue(self.p2p.content_item_exists(slug))

        # delete it
        self.p2p.delete_content_item(slug)

        # make sure it does not exits.
        self.assertFalse(self.p2p.content_item_exists(slug))

    def test_create_update_delete_htmlstory(self):
        data = {
            'slug': 'la_na_test_create_update_delete-htmlstory',
            'title': 'Testing creating, updating and deletion',
            'body': 'Updated info 2',
            'content_item_type_code': 'htmlstory',
        }

        try:
            result = self.p2p.create_content_item(data)
        except P2PSlugTaken:
            self.p2p.delete_content_item(data['slug'])
            result = self.p2p.create_content_item(data)

        data2 = data.copy()
        data2['body'] = 'Lorem ipsum foo bar 2'
        result2 = self.p2p.update_content_item(data2)
        self.assertTrue(self.p2p.delete_content_item(data['slug']))

        self.assertIn(
            'html_story',
            list(result.keys())
        )
        res = result['html_story']
        self.assertEqual(res['slug'], data['slug'])
        self.assertEqual(res['title'], data['title'])
        self.assertEqual(res['body'].strip(), data['body'])

        res = result2
        self.assertEqual(res, {})

    def test_preserve_embedded_tags(self):
        data = {
            'slug': 'la_na_test_create_update_delete-htmlstory',
            'title': 'Testing creating, updating and deletion',
            'body': 'lorem ipsum 3',
            'content_item_type_code': 'htmlstory',
        }

        try:
            result = self.p2p.create_content_item(data)
        except P2PSlugTaken:
            self.p2p.delete_content_item(data['slug'])
            result = self.p2p.create_content_item(data)

        data2 = data.copy()
        data2['body'] = 'Lorem ipsum foo bar'
        result2 = self.p2p.update_content_item(data2)
        self.assertTrue(self.p2p.delete_content_item(data['slug']))

        self.assertIn(
            'html_story',
            list(result.keys())
        )
        res = result['html_story']
        self.assertEqual(res['slug'], data['slug'])
        self.assertEqual(res['title'], data['title'])
        self.assertEqual(res['body'].strip(), data['body'])

        res = result2
        self.assertEqual(res, {})

    def test_right_rail(self):
        data = {
            'slug': 'la_na_test_create_update_delete-htmlstory',
            'title': 'Testing creating, updating and deletion',
            'body': 'lorem ipsum 4',
            'content_item_type_code': 'htmlstory',
        }

        try:
            result = self.p2p.create_content_item(data)['html_story']
        except P2PSlugTaken:
            self.p2p.delete_content_item(data['slug'])
            result = self.p2p.create_content_item(data)['html_story']

        self.p2p.hide_right_rail(result['slug'])
        self.p2p.show_right_rail(result['slug'])
        self.assertTrue(self.p2p.delete_content_item(data['slug']))

    def test_robots(self):
        data = {
            'slug': 'la_na_test_create_update_delete-htmlstory',
            'title': 'Testing creating, updating and deletion',
            'body': 'lorem ipsum 5',
            'content_item_type_code': 'htmlstory',
        }

        try:
            result = self.p2p.create_content_item(data)['html_story']
        except P2PSlugTaken:
            self.p2p.delete_content_item(data['slug'])
            result = self.p2p.create_content_item(data)['html_story']

        self.p2p.hide_to_robots(result['slug'])
        self.p2p.show_to_robots(result['slug'])
        self.assertTrue(self.p2p.delete_content_item(data['slug']))

    def test_multi_items(self):
        """
        Try sending in 3 ids to get_multi_content_items and assert that it
        returns the IDs we passed in.
        """
        # Grab the IDs
        ci_ids = []
        for slug in self.test_story_slugs[:3]:
            ci = self.p2p.get_content_item(slug)
            ci_ids.append(ci["id"])

        # Make the call
        data = self.p2p.get_multi_content_items(ci_ids)

        # Ensure the first item has all the keys we expect
        for k in self.content_item_keys:
            self.assertIn(k, list(data[0].keys()))

        # Loop through each content item and ensure the ID
        # matches what was passed in to get_multi_content_items
        for i, ci in enumerate(data):
            self.assertEqual(data[i]["id"], ci_ids[i])

    def test_fancy_content_item(self):
        self.p2p.push_into_content_item(
            self.first_test_story_slug,
            [self.test_htmlstory_slug]
        )
        data = self.p2p.get_fancy_content_item(
            self.first_test_story_slug
        )

        for k in ('title', 'id', 'slug'):
            self.assertIn(k, data['related_items'][0]['content_item'])

    def test_get_revision_list_and_number(self):
        data = self.p2p.get_content_item_revision_list(
            self.first_test_story_slug, 1
        )
        self.assertEqual(type(data["revisions"]), list)
        number = data["revisions"][1]["number"]
        data2 = self.p2p.get_content_item_revision_number(
            self.first_test_story_slug, number
        )
        self.assertEqual(type(data2), dict)

    def test_get_kickers(self):
        data = self.p2p.get_kickers({"product_affiliate_code":"lanews"})
        self.assertEqual(type(data["kickers"]), list)

    def test_get_section(self):
        data = self.p2p.get_section('/local')
        self.assertEqual(type(data), dict)

    def test_create_delete_collection(self):
        try:
            self.p2p.delete_collection('la_test_api_create')
        except P2PNotFound:
            pass

        data = self.p2p.create_collection({
            'code': 'la_test_api_create',
            'name': 'Test collection created via API',
            'section_path': '/test'
        })

        self.assertEqual(data['code'], 'la_test_api_create')
        self.assertEqual(data['name'], 'Test collection created via API')

        data = self.p2p.delete_collection('la_test_api_create')

        self.assertEqual(
            data,
            "Collection 'la_test_api_create' destroyed successfully"
        )

    def test_search_collections(self):
        # Create dummy collection
        collection_code = "la_test_search_collections"
        collection_name = "Collection to test search functionality"
        try:
            data = self.p2p.create_collection({
                'code': collection_code,
                'name': collection_name,
                'section_path': '/test'
            })
        except P2PSlugTaken:
            pass

        # Get results from collection search, check we can get a name from it
        results = self.p2p.search_collections(collection_code)
        test_name = results[0]['name']
        self.assertEqual(len(results), 1)

        results = self.p2p.search_collections(collection_code, 10)
        self.assertEqual(len(results), 1)

        results = self.p2p.search_collections(collection_code, product_affiliate_code='lanews')
        self.assertEqual(len(results), 1)

        results = self.p2p.search_collections('la-foobazbar')
        self.assertEqual(len(results), 0)

        # Cleanup and test
        self.p2p.delete_collection(collection_code)
        self.assertEqual(test_name, collection_name)

    def test_publish_story(self):
        """
        Here we are going to create a story, create a photo, attach the photo
        to the story, create a collection, add the story to the collection, and
        supress the story in the collection.
        """
        article_data = {
            'slug': 'la_na_test_create_update_delete',
            'title': 'Testing creating, updating and deletion',
            'byline': 'By Bobby Tables',
            'body': 'lorem ipsum 7',
            'content_item_type_code': 'story',
        }
        photo_data = {
            'slug': 'la_na_test_create_update_delete_photo',
            'title': 'Photo: Testing creating, updating and deletion',
            'caption': 'lorem ipsum 8',
            'content_item_type_code': 'photo',
            'photo_upload': {
                'alt_thumbnail': {
                    'url': 'http://media.apps.chicagotribune.com/api_test.jpg'
                }
            }
        }

        # make sure we're clean
        try:
            self.p2p.delete_content_item(photo_data['slug'])
            self.p2p.delete_content_item(article_data['slug'])
        except P2PNotFound:
            pass

        article = photo = None
        try:
            # Create article
            article = self.p2p.create_content_item(article_data)
            self.assertIn('story', article)
            self.assertEqual(
                article['story']['slug'], article_data['slug'])

            # Create photo
            photo = self.p2p.create_content_item(photo_data)
            self.assertIn('photo', photo)
            self.assertEqual(
                photo['photo']['slug'], photo_data['slug'])

            # Add photo as related item to the article
            self.assertEqual(
                self.p2p.push_into_content_item(
                    article_data['slug'], [photo_data['slug']]),
                {})

            # Add article to a collection
            self.assertEqual(
                self.p2p.push_into_collection(
                    self.first_test_collection_code,
                    [article_data['slug']]
                ),
                {}
            )

            # Suppress the article in the collection
            self.assertEqual(
                self.p2p.suppress_in_collection(
                    self.first_test_collection_code,
                    [article_data['slug']]
                ),
                {}
            )
        finally:
            # Delete the photo
            if photo:
                self.assertTrue(self.p2p.delete_content_item(
                    photo_data['slug']))
            # Delete the article
            if article:
                self.assertTrue(self.p2p.delete_content_item(
                    article_data['slug']))

    def test_file_url_not_found_error(self):
        """
        Tests that sending a bad photo url to p2p will raise
        P2PFileURLNotFound.
        """
        # Try sending a bad URL
        bad_photo_url = "http://www.latimes.com/bad_photo_url.png"
        payload = {
            'slug': self.first_test_story_slug,
            'content_item_type_code': 'htmlstory',
            'photo_upload': {
                'alt_thumbnail': {
                    'url': bad_photo_url
                }
            },
        }
        with self.assertRaises(P2PFileURLNotFound):
            self.p2p.create_or_update_content_item(payload)

        # Now try sending a good URL
        good_photo_url = "https://placeholdit.imgix.net/~text?txtsize=33&\
txt=P2P%20UNIT%20TEST&w=600&h=400"
        payload["photo_upload"]["alt_thumbnail"]["url"] = good_photo_url

        self.p2p.create_or_update_content_item(payload)

class TestFilters(unittest.TestCase):

    def test_get_body(self):
        self.assertEqual(filters.get_body({}), '')
        self.assertEqual(filters.get_body({'caption': 'foo'}), '<p>foo</p>')
        self.assertEqual(filters.get_body({'body': 'foo'}), '<p>foo</p>')
        self.assertEqual(
            filters.get_body({'body': "foo\n\nfoo"}),
            '<p>foo</p>\n\n<p>foo</p>')
        self.assertEqual(
            filters.get_body({'body': 'foo<br/> <br >foo'}),
            '<p>foo</p>\n\n<p>foo</p>')
        self.assertEqual(
            filters.get_body({'body': '<p>foo<br/> <br >foo</p>'}),
            '<p>foo</p>\n\n<p>foo</p>')
        self.assertEqual(
            filters.get_body({'body': '<p>foo<br/>&nbsp;<br >foo</p>'}),
            '<p>foo</p>\n\n<p>foo</p>')
        self.assertEqual(
            filters.get_body({'body': '<p>foo<br/>foo<br>&nbsp;<br >foo</p>'}),
            '<p>foo<br/>foo</p>\n\n<p>foo</p>')

    def test_get_brief(self):
        self.assertEqual(filters.get_brief({'abstract': 'foo'}), 'foo')
        self.assertEqual(
            filters.get_brief({'content_item': {'body': 'foo'}}),
            'foo')

    def test_get_head(self):
        self.assertEqual(filters.get_headline({'title': 'foo'}), 'foo')
        self.assertEqual(
            filters.get_headline({'headline': 'foo'}), 'foo')
        self.assertEqual(
            filters.get_headline({'content_item': {'title': 'foo'}}), 'foo')

    def test_get_url(self):
        self.assertEqual(
            filters.get_url({'web_url': 'bar'}), 'bar')
        self.assertEqual(
            filters.get_url({'url': 'foo', 'web_url': 'bar'}), 'bar')
        self.assertEqual(
            filters.get_url({
                'content_item_type_code': 'storylink',
                'url': 'foo',
                'web_url': 'bar'
            }), 'foo')

    def test_get_thumb_url(self):
        self.assertEqual(
            filters.get_thumb_url({}, 600), '')
        self.assertEqual(
            filters.get_thumb_url({
                'alt_thumbnail_url': 'http://www.trbimg.com/foo/187/16x9'
            }, 600), 'http://www.trbimg.com/foo/600')
        self.assertEqual(
            filters.get_thumb_url({
                'thumbnail_url': 'http://www.trbimg.com/foofoo/187/16x9'
            }, 600, '1x1'), 'http://www.trbimg.com/foofoo/600/1x1')
        self.assertEqual(
            filters.get_thumb_url({
                'photo_services_url': 'http://www.trbimg.com/foofoo'
            }, 400), 'http://www.trbimg.com/foofoo/400')

    def test_get_time(self):
        self.assertEqual(
            filters.get_time({'display_time': 'foo'}),
            'foo')
        self.assertEqual(
            filters.get_time({'content_item': {'display_time': 'foo'}}),
            'foo')
        self.assertEqual(
            filters.get_time({'content_item': {'create_time': 'foo'}}),
            'foo')

    def test_get_featured_related_item(self):
        self.assertEqual(
            filters.get_featured_related_item({
                'content_item': {
                    'related_items': [
                        {'content_item_type_code': 'article'},
                        {'content_item_type_code': 'storylink'},
                        {'content_item_type_code': 'photogallery'},
                        {'content_item_type_code': 'photo'}
                    ]
                }
            }), {'content_item_type_code': 'photogallery'})

    def test_find_content_item(self):
        self.assertEqual(
            filters.find_content_item({'content_item': {'foo': 'bar'}}),
            {'foo': 'bar'})
        self.assertEqual(
            filters.find_content_item({'foo': 'bar'}),
            {'foo': 'bar'})

    def test_br_to_space(self):
        self.assertEqual(
            filters.br_to_space('foo<br> <br />foo'),
            'foo foo')
        self.assertEqual(
            filters.br_to_space('foo<br/>&nbsp;<br/>foo'),
            'foo foo')

    def test_split_paragraphs(self):
        self.assertEqual(
            filters.split_paragraphs('<p>foo</p> <p>foo</p>'),
            ['<p>foo</p>', '<p>foo</p>'])

    def test_br_to_p(self):
        self.assertEqual(
            filters.br_to_p('foo<br> <br />foo'),
            '<p>foo</p>\n\n<p>foo</p>')
        self.assertEqual(
            filters.br_to_p('foo<br/>&nbsp;<br/>foo'),
            '<p>foo</p>\n\n<p>foo</p>')

    def test_section_heads(self):
        self.assertEqual(
            filters.section_heads('<p>foo</p> <p><b>head</b></p> <p>foo</p>'),
            '<p>foo</p> <h4>head</h4> <p>foo</p>')

    def test_strip_runtime_tags(self):
        self.assertEqual(
            filters.strip_runtime_tags(
                '<p>foo <runtime:topic>obama</runtime:topic> foo</p><p>foo</p>'
            ),
            '<p>foo obama foo</p><p>foo</p>'
        )

    def test_strip_tags(self):
        self.assertEqual(
            filters.strip_tags('<p>foo</p> <p><b>head</b></p> <p>foo</p>'),
            'foo head foo')



class CollectionTest(BaseP2PTest):
    """
    P2P collection tests
    """
    @classmethod
    def setUpClass(cls):
        cls.setUpTestStories()
        cls.setUpTestCollections()

    def test_get_collection(self):
        data = self.p2p.get_collection(self.first_test_collection_code)
        for k in self.collection_keys:
            self.assertIn(k, list(data.keys()))

    def test_get_collection_layout(self):
        test_item = {
            'slug': 'la_na_test_two_collections',
            'title': 'Testing updating collections in content items',
            'body': 'lorem ipsum 6',
            'content_item_type_code': 'story',
        }

        try:
            self.p2p.create_content_item(test_item)
        except P2PSlugTaken:
            pass

        self.p2p.push_into_collection(
            self.first_test_collection_code, [test_item['slug']]
        )

        data = self.p2p.get_collection_layout(self.first_test_collection_code)

        for k in self.content_layout_keys:
            self.assertIn(k, list(data.keys()))

        for k in self.content_layout_item_keys:
            self.assertIn(k, list(data['items'][0].keys()))

        self.p2p.delete_content_item(test_item['slug'])

    def test_fancy_collection(self):
        test_item = {
            'slug': 'la_na_test_two_collections',
            'title': 'Testing updating collections in content items',
            'body': 'lorem ipsum 6',
            'content_item_type_code': 'story',
        }

        try:
            self.p2p.create_content_item(test_item)
        except P2PSlugTaken:
            pass

        self.p2p.push_into_collection(
            self.first_test_collection_code, [test_item['slug']]
        )

        data = self.p2p.get_fancy_collection(
            self.first_test_collection_code,
            with_collection=True
        )

        for k in self.content_layout_keys:
            self.assertIn(k, list(data.keys()))

        for k in self.collection_keys:
            self.assertIn(k, list(data['collection'].keys()))

        self.assertTrue(len(data['items']) > 0)

        for k in self.content_layout_item_keys:
            self.assertIn(k, list(data['items'][0].keys()))

        self.p2p.delete_content_item(test_item['slug'])

    def test_that_unique_contraint_exception_is_raised(self):
        """
        Tests that pushing duplicate items into a collection raises
        P2PUniqueConstraintViolated()
        """
        # First remove the item
        self.p2p.remove_from_collection(
            self.first_test_collection_code,
            [self.first_test_story_slug]
        )

        # Successfully push the item in
        try:
            self.p2p.push_into_collection(
                self.first_test_collection_code,
                [self.first_test_story_slug]
            )
        except P2PUniqueConstraintViolated:
            self.fail("P2PUniqueConstraintViolated shouldn't have been raised")

        # Assert that the second time pushed in, the exception is raised
        with self.assertRaises(P2PUniqueConstraintViolated):
            self.p2p.push_into_collection(
                self.first_test_collection_code,
                [self.first_test_story_slug]
            )

    def test_push_item_into_two_collections(self):
        data = {
            'slug': 'la_na_test_two_collections',
            'title': 'Testing updating collections in content items',
            'body': 'lorem ipsum 6',
            'content_item_type_code': 'story',
        }

        try:
            self.p2p.create_content_item(data)
        except P2PSlugTaken:
            pass

        self.p2p.push_into_collection(
            self.first_test_collection_code, [data['slug']]
        )

        data2 = data.copy()
        data2['body'] = 'Lorem ipsum foo bar'

        self.p2p.push_into_collection(
            self.second_test_collection_code,
            [data['slug']]
        )

        self.p2p.update_content_item(data2)

        first_collection_data = self.p2p.get_fancy_collection(
            self.first_test_collection_code
        )

        content_item_included = False
        for item in first_collection_data['items']:
            if item['slug'] == data['slug']:
                content_item_included = True

        second_collection_data = self.p2p.get_fancy_collection(
            self.second_test_collection_code
        )

        content_item_included_again = False
        for item in second_collection_data['items']:
            if item['slug'] == data['slug']:
                content_item_included_again = True

        self.assertTrue(content_item_included)
        self.assertTrue(content_item_included_again)

        self.assertTrue(self.p2p.delete_content_item(data['slug']))

    def test_many_multi_items(self):
        self.p2p.remove_from_collection(
            self.first_test_collection_code,
            self.test_story_slugs
        )
        self.p2p.push_into_collection(
            self.first_test_collection_code,
            self.test_story_slugs
        )

        clayout = self.p2p.get_collection_layout(
            self.first_test_collection_code
        )
        ci_ids = [i['contentitem_id'] for i in clayout['items']]

        self.assertTrue(len(ci_ids) > 7)

        data = self.p2p.get_multi_content_items(ci_ids)
        self.assertTrue(len(ci_ids) == len(data))
        for k in self.content_item_keys:
            self.assertIn(k, list(data[0].keys()))

    def test_that_converting_to_array_works(self):
        """
        Test that passing in a string in place of an array results in a successful call
        """
        # First just remove it from the test collection to make sure we can push
        try:
            self.p2p.remove_from_collection(
                self.first_test_collection_code,
                self.first_test_story_slug
            )
        except:
            pass

        # Then push with a slug string
        self.p2p.push_into_collection(
            self.first_test_collection_code,
            self.first_test_story_slug
        )

        # Then remove with a slug string
        self.p2p.remove_from_collection(
            self.first_test_collection_code,
            self.first_test_story_slug
        )
