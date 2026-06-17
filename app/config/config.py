from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource


class Config(BaseSettings):
    model_config = SettingsConfigDict(yaml_file="config.yaml", extra="allow")

    bot_token: str

    gofinance_username: str

    gofinance_password: str

    gofinance_base_url: str

    @classmethod
    def settings_customise_sources(cls, settings_cls, **kwargs):
        return (YamlConfigSettingsSource(settings_cls=settings_cls),)


config = Config()
