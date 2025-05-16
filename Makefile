##
#
#   The pyroute2 project is dual licensed, see README.license.md for details
#
#
python ?= $(shell util/find_python.sh)
releaseTag ?= $(shell git describe --tags --abbrev=0)
releaseDescription := $(shell git tag -l -n1 ${releaseTag} | sed 's/[0-9. ]\+//')
noxboot ?= ~/.venv-boot

define nox
        {\
		which nox 2>/dev/null || {\
		    test -d ${noxboot} && \
				{\
					. ${noxboot}/bin/activate;\
				} || {\
					${python} -m venv ${noxboot};\
					. ${noxboot}/bin/activate;\
					pip install --upgrade pip;\
					pip install nox;\
				};\
		};\
		nox $(1) -- '${noxconfig}';\
	}
endef

.PHONY: all
all:
	@echo targets:
	@echo
	@echo \* clean -- clean all generated files
	@echo \* docs -- generate project docs
	@echo \* dist -- create the package file
	@echo \* test -- run all the tests
	@echo \* install -- install lib into the system or the current virtualenv
	@echo \* uninstall -- uninstall lib
	@echo

.PHONY: git-clean
git-clean:
	git clean -d -f -x
	git remote prune origin
	git branch --merged | grep -vE '(^\*| master )' >/tmp/merged-branches && \
		( xargs git branch -d </tmp/merged-branches ) ||:

.PHONY: clean
clean:
	@rm -rf dist
	@rm -rf build

.PHONY: docs
docs:
	$(call nox,-e docs)

.PHONY: format
format:
	$(call nox,-e linter-$(shell basename ${python}))

.PHONY: test nox
test nox:
	$(call nox,-e ${session})

.PHONY: upload
upload: dist
	$(call nox,-e upload)

.PHONY: release
release: dist
	gh release create \
		--verify-tag \
		--title "${releaseDescription}" \
		${releaseTag} \
		./dist/*${releaseTag}*

.PHONY: setup
setup:
	$(MAKE) VERSION

.PHONY: dist
dist: setup
	$(call nox,-e build)

.PHONY: install
install: setup
	$(MAKE) uninstall
	$(MAKE) clean
	$(call nox,-e build)
	${python} -m pip install dist/pyroutex-*whl ${root}

.PHONY: uninstall
uninstall:
	${python} -m pip uninstall -y pyroutex
