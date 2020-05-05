ifndef stack-name
$(error stack-name is not set)
endif
# ifndef revision
# revision := $(shell date --utc +%Y%m%dT%H%M%SZ)
# endif

profile-opt := --profile $(profile-name)
region-opt := --region $(region-name)



define getRef
$(shell aws cloudformation describe-stacks \
	--stack-name $(stack-name) \
	--query "Stacks[0].Outputs[?OutputKey=='$(1)'].OutputValue" \
	$(profile-opt) \
	$(region-opt) \
	--output text)
endef
APPLICATION := $(call getRef,CodeDeployApplication)
DEPLOYMENT_GROUP := $(call getRef,CodeDeployDeploymentGroup)
DEPLOYMENTS_BUCKET := $(call getRef,DeploymentsBucket)


PACKAGE := $(stack-name)_$(revision).tgz


package:
	cd airflow && tar czf ../$(PACKAGE) .

upload: package
	aws s3 cp $(PACKAGE) s3://$(DEPLOYMENTS_BUCKET) $(profile-opt)

deploy: upload
	aws deploy create-deployment \
		--application-name $(APPLICATION) \
		--deployment-group-name $(DEPLOYMENT_GROUP) \
		--s3-location bucket=$(DEPLOYMENTS_BUCKET),bundleType=tgz,key=$(PACKAGE) \
		--deployment-config-name CodeDeployDefault.AllAtOnce \
		--file-exists-behavior OVERWRITE \
	    $(profile-opt)\
	    $(region-opt)
