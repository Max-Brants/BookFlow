import type { ComponentType, ReactNode } from 'react';

import { useLanguage } from '../../../contexts/LanguageContext';
import { BestsellerAdminStatus } from './BestsellerAdminStatus';
import { NamingTemplateField } from './NamingTemplateField';
import { OidcAdminHint } from './OidcAdminHint';
import { OidcEnvInfo } from './OidcEnvInfo';
import { SettingsLabel } from './SettingsLabel';
import type {
  CustomSettingsFieldLayout,
  CustomSettingsFieldLayoutContext,
  CustomSettingsFieldRendererProps,
} from './types';
import { UsersManagementField } from './UsersManagementField';

type CustomFieldRenderer = ComponentType<CustomSettingsFieldRendererProps>;
type CustomFieldLayoutResolver = (
  context: CustomSettingsFieldLayoutContext,
) => CustomSettingsFieldLayout;

interface CustomFieldDefinition {
  renderer: CustomFieldRenderer;
  getLayout?: CustomFieldLayoutResolver;
}

const CUSTOM_FIELD_DEFINITIONS: Record<string, CustomFieldDefinition> = {
  bestseller_admin_status: {
    renderer: BestsellerAdminStatus,
  },
  users_management: {
    renderer: UsersManagementField,
    getLayout: () => {
      return {
        takeOverTab: false,
      };
    },
  },
  naming_template: {
    renderer: NamingTemplateField,
  },
  settings_label: {
    renderer: SettingsLabel,
  },
  oidc_admin_hint: {
    renderer: OidcAdminHint,
  },
  oidc_env_info: {
    renderer: OidcEnvInfo,
  },
};

const UnknownCustomField = ({ component }: { component: string }) => {
  const { t } = useLanguage();
  return (
    <p className="text-xs opacity-60">{t('settings.unknownCustomComponent', { component })}</p>
  );
};

export const renderCustomSettingsField = (props: CustomSettingsFieldRendererProps): ReactNode => {
  const definition = CUSTOM_FIELD_DEFINITIONS[props.field.component];
  const Renderer = definition?.renderer;
  if (!Renderer) {
    return <UnknownCustomField component={props.field.component} />;
  }
  return <Renderer {...props} />;
};

export const getCustomSettingsFieldLayout = (
  context: CustomSettingsFieldLayoutContext,
): CustomSettingsFieldLayout => {
  const definition = CUSTOM_FIELD_DEFINITIONS[context.field.component];
  if (!definition?.getLayout) {
    return {};
  }
  return definition.getLayout(context);
};

export type { CustomSettingsFieldLayout } from './types';
