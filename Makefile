.PHONY: test ship testcollectionsearch

name='foo'

test:
	clear
	@if [ $(name) = 'foo' ]; then \
		echo "Running all tests";\
		coverage run setup.py test;\
		coverage report -m;\
	else \
		echo "Running provided test";\
		python -m unittest p2p.tests.$(name);\
	fi

ship:
	python setup.py sdist bdist_wheel
	twine upload dist/* --skip-existing
