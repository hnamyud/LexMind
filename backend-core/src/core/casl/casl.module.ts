import { Module, Global } from '@nestjs/common';
import { CaslAbilityFactory } from './ability.factory';

@Global()
@Module({
    providers: [CaslAbilityFactory],
    exports: [CaslAbilityFactory]
})
export class CaslModule { }