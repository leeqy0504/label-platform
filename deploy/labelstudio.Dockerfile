FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/heartexlabs/label-studio:1.21.0

USER root

COPY deploy/labelstudio-delete-button.js /label-studio/label_studio/core/static/js/label-platform-delete-button.js
COPY deploy/labelstudio-delete-button.js /label-studio/label_studio/core/static_build/js/label-platform-delete-button.js

RUN chmod 0644 \
      /label-studio/label_studio/core/static/js/label-platform-delete-button.js \
      /label-studio/label_studio/core/static_build/js/label-platform-delete-button.js \
    && sed -i 's#</body>#  <script src="{{settings.HOSTNAME}}/static/js/label-platform-delete-button.js?v=3"></script>\n</body>#' \
      /label-studio/label_studio/templates/base.html

USER 1001
